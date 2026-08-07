"""Crazyflie controller for the standalone QT ground station.

Owns the radio link (Crazyradio PA), telemetry logging, and every flight
command.  This module has NO Qt dependency on purpose: it is used by the
GUI, the headless CLI, and the local HTTP command server, so OpenClaw can
operate the drone with or without a window open.

Safety model (mirrors extension/simple_crazyflie/04_flying.py):
  * Custom CRTP v6 firmware: the ONLY arming switch is the system.arm
    parameter; cflib's platform arming request is silently ignored.
  * motorPowerSet.enable must be 0 for normal flight (a previous propeller
    check may have left it = 1, which overrides the flight controller).
  * The LOCKED supervisor state (supervisor.info bit 6) can only be
    cleared by a power cycle; takeoff is refused while it is set.
  * Altitude hold uses TYPE_HOVER_LEGACY hover setpoints pumped at 20 Hz
    (the packet this firmware expects).  Landings ramp down and then hold
    z=0 for a couple of seconds before the motors are cut, otherwise the
    supervisor latches LOCKED.
  * A dead-man switch: while flying, a move command expires after
    MOVE_WATCHDOG_S seconds and the drone is put back into a hover.
"""

import logging
import json
import os
import queue
import threading
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

# --------------------------------------------------------------------------- #
# Firmware quirks & tuning
# --------------------------------------------------------------------------- #

LOCKED_BIT = 0x40          # supervisor.info bit 6 -> power cycle required
RATE = 20.0                # Hz, hover-setpoint pump rate
STEP = 1.0 / RATE

TAKEOFF_TIME = 3.0         # s, ramp 0 -> target height
LAND_TIME = 3.0            # s, ramp target -> 0
SETTLE_TIME = 2.0          # s, z=0 hold before cutting motors (avoid LOCKED)
MOVE_WATCHDOG_S = 0.5      # s, stale move command -> hover
LINK_WATCHDOG_S = 3.5      # s, no telemetry packet -> treat link as dead
LINK_STALE_BREAK_S = 1.0   # s, long loops exit early once the link is stale
CONNECT_TIMEOUT_S = 15.0   # s, abandon a stuck radio connection attempt
ESTOP_UNLOCK_OFFLINE_S = 10.0  # s, offline before reconnect => drone restart

BATTERY_TAKEOFF_MIN_V = 3.7
BATTERY_WARN_V = 3.8
MAX_Z_HOLD = 2.5           # m, hard ceiling for the altitude-hold setpoint
MAX_HEIGHT = 1.5           # m, takeoff target clamp

SPIN_MOTORS = ("m1", "m2", "m3", "m4")
SPIN_POWER = 4000          # ~6% of 65535 -> slow, safe individual spin
SPIN_TIME = 2.0            # s per motor

# Suppress the harmless cflib warnings this custom firmware triggers.
warnings.filterwarnings(
    "ignore", message=r"Using legacy TYPE_.*_LEGACY", category=DeprecationWarning
)
warnings.filterwarnings(
    "ignore", message=r"platform\.send_arming_request is deprecated",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"The supervisor subsystem requires CRTP protocol version 12 or later",
    category=UserWarning,
)
logging.getLogger("cflib").setLevel(logging.ERROR)


class CrazyflieController:
    """Thread-safe wrapper around one Crazyflie radio connection.

    Commands are queued with :meth:`request` and executed on a background
    thread that owns the SyncCrazyflie context (cflib objects are not
    thread-safe).  Latest telemetry is available via :meth:`snapshot`.
    """

    def __init__(self, uri, cache_dir=None):
        self.uri = uri
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._cache_dir = cache_dir or os.path.join(base, "cache")
        os.makedirs(self._cache_dir, exist_ok=True)

        self._commands = queue.Queue()
        # High-priority channel: estop/stop bypass the normal queue so an
        # emergency cut is never delayed behind a long move/ramp command.
        self._urgent = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._scf = None
        self._estop_latched = False
        self._offline_since = None

        self._lock = threading.Lock()
        self._snapshot = {
            "connected": False,
            "flying": False,
            "armed": False,
            "locked": False,
            "estop_latched": False,
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
            "battery_v": 0.0,
            "link_quality": 0.0,
            "supervisor_info": 0,
            "last_update": 0.0,
            "last_error": None,
        }

        # Flight state (owned by the worker thread)
        self._z_hold = 0.0
        self._last_move = 0.0
        self._flying = False
        self._armed = False

        self._log_lines = queue.Queue(maxsize=500)
        self._load_estop_latch()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start(self):
        """Initialise CRTP drivers and start the worker thread."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self, timeout=10):
        """Request a motor cut, stop the worker, and wait for it."""
        if self._thread is None:
            return
        self.request("stop")
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    def request(self, action, **kwargs):
        """Queue a command.  Actions: takeoff/land/hover/stop/estop/move.

        ``estop`` and ``stop`` go through the urgent channel and are picked
        up by the worker within one pump cycle (~10 ms), even while a
        long-running move/takeoff/land is being executed.
        """
        if action in ("estop", "stop"):
            if action == "estop":
                self._set_estop_latch(True)
            self._urgent.put({"action": action, **kwargs})
        else:
            self._commands.put({"action": action, **kwargs})

    def emergency_stop(self):
        """Queue an immediate motor cut (alias for request('estop'))."""
        self.request("estop")

    def clear_estop_latch(self):
        """Manual unlock by a human at the ground station.

        The auto-unlock path only fires after a confirmed drone restart;
        this is the operator override for situations verified as safe
        (drone on the ground, props clear).  Intentionally NOT exposed
        over HTTP so remote agents (e.g. OpenClaw via WeChat) can never
        clear the latch themselves.
        """
        if self._estop_latched:
            self._log("[GS] E-STOP latch cleared manually by operator")
        self._set_estop_latch(False)

    def snapshot(self):
        """Thread-safe copy of the latest telemetry + state."""
        with self._lock:
            return dict(self._snapshot)

    def drain_log(self):
        """Return and clear all pending log lines."""
        lines = []
        while True:
            try:
                lines.append(self._log_lines.get_nowait())
            except queue.Empty:
                break
        return lines

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #

    def _worker(self):
        cflib.crtp.init_drivers()
        while not self._stop.is_set():
            try:
                self._connect_once()
            except Exception as exc:
                self._scf = None
                self._set("connected", False)
                self._set("flying", False)
                self._set("armed", False)
                self._set("last_error", str(exc))
                if self._offline_since is None:
                    self._offline_since = time.time()
                self._log(f"[GS] Link error: {exc}")
            if not self._stop.is_set():
                time.sleep(2.0)

    def _connect_once(self):
        """One connection attempt with a hard timeout *for the connect
        phase only*.  Once the link is established the worker stays inside
        the attempt thread until the link drops or the app stops; the
        watchdog (``_link_stale``) is what ends a dead link.

        The timeout protects against a radio driver stuck in a low-level
        retry loop during ``open_link`` — it must never fire on a healthy,
        long-lived connection."""
        result = {}
        connected = threading.Event()

        def _attempt():
            try:
                with SyncCrazyflie(
                    self.uri, cf=Crazyflie(rw_cache=self._cache_dir)
                ) as scf:
                    connected.set()
                    self._scf = scf
                    self._set("connected", True)
                    self._set("last_error", None)
                    self._log(f"[GS] Connected: {self.uri}")
                    self._maybe_clear_estop_latch()
                    self._setup_logging(scf.cf)
                    # Detect link loss even when cflib stays silent: a dead
                    # drone stops producing telemetry long before any
                    # higher-level driver would raise.
                    scf.cf.connection_lost.add_callback(
                        lambda uri, msg: self._on_link_lost(msg)
                    )
                    scf.cf.disconnected.add_callback(
                        lambda uri: self._on_link_lost("disconnected")
                    )
                    time.sleep(0.5)
                    self._reset_motor_overrides(scf.cf)
                    while not self._stop.is_set():
                        if self._link_stale():
                            raise RuntimeError(
                                f"link lost: no telemetry for {LINK_WATCHDOG_S}s"
                            )
                        self._pump(scf.cf)
                        time.sleep(0.005)
            except Exception as exc:
                result["exc"] = exc

        thread = threading.Thread(target=_attempt, daemon=True)
        thread.start()
        # Wait only for the *connect* phase: the link is up as soon as the
        # event fires, after which the thread runs for the connection's
        # lifetime and we must not time it out.
        if not connected.wait(timeout=CONNECT_TIMEOUT_S):
            # Connection never completed -> radio driver likely stuck.
            # Join briefly (best effort) and let the outer loop retry.
            thread.join(timeout=2.0)
            self._scf = None
            self._set("connected", False)
            self._set("flying", False)
            self._set("armed", False)
            self._set("last_error", "connect timeout (radio driver stuck)")
            if self._offline_since is None:
                self._offline_since = time.time()
            self._log("[GS] Connect attempt timed out, will retry")
            return
        # Link established: block until the attempt thread ends (link lost
        # or stop requested), then propagate any link error.
        thread.join()
        if "exc" in result and not self._stop.is_set():
            raise result["exc"]

    def _on_link_lost(self, msg):
        """cflib reported the link died (or telemetry went stale)."""
        self._set("connected", False)
        self._set("flying", False)
        self._set("armed", False)
        self._set("last_error", f"link lost: {msg}")
        if self._offline_since is None:
            self._offline_since = time.time()
        self._log(f"[GS] Link lost: {msg} (reconnecting...)")

    def _link_stale(self):
        with self._lock:
            last = self._snapshot.get("last_update") or 0.0
        return bool(last) and (time.time() - last) > LINK_WATCHDOG_S

    def _pump(self, cf):
        # 1) Urgent commands first: an emergency cut must win immediately.
        try:
            urgent = self._urgent.get_nowait()
        except queue.Empty:
            urgent = None
        if urgent is not None:
            self._dispatch(cf, urgent)
            # Discard stale normal commands queued before/around the
            # emergency so a queued takeoff cannot re-arm the drone.
            self._drain_normal_commands()
            return
        # 2) Regular commands.
        try:
            cmd = self._commands.get_nowait()
        except queue.Empty:
            cmd = None
        if cmd is not None:
            self._dispatch(cf, cmd)
        self._watchdog(cf)

    def _drain_normal_commands(self):
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def _emergency_pending(self):
        """True when an urgent cut is waiting — long loops exit promptly."""
        return not self._urgent.empty()

    def _dispatch(self, cf, cmd):
        action = cmd.get("action")
        try:
            if action == "takeoff":
                self._takeoff(cf, float(cmd.get("height", 0.3)))
            elif action == "land":
                self._land(cf)
            elif action == "hover":
                self._hover(cf)
            elif action == "stop":
                self._cut(cf, reason="stop")
            elif action == "estop":
                self._cut(cf, reason="EMERGENCY")
            elif action == "move":
                duration = float(cmd.get("duration") or 0.0)
                if duration > 0:
                    deadline = time.monotonic() + duration
                    while (
                        time.monotonic() < deadline
                        and not self._stop.is_set()
                        and not self._emergency_pending()
                    ):
                        self._move(cf, cmd)
                    self._hover(cf)  # stop drifting after the timed move
                else:
                    self._move(cf, cmd)
            elif action == "spin_test":
                self._spin_test(cf, cmd)
            else:
                self._log(f"[GS] Unknown command: {action}")
        except Exception as exc:
            self._log(f"[GS] Command '{action}' failed: {exc}")

    # ------------------------------------------------------------------ #
    # Flight actions
    # ------------------------------------------------------------------ #

    def _takeoff(self, cf, height):
        if self._flying:
            self._log("[GS] Takeoff ignored: already flying")
            return
        if self._snapshot["locked"]:
            self._log(
                "[GS] REFUSED takeoff: drone is LOCKED "
                "(power-cycle the drone first)"
            )
            return
        if self._estop_latched:
            self._log(
                "[GS] REFUSED takeoff: E-STOP latched "
                "(power-cycle the drone to unlock)"
            )
            return
        vbat = self._snapshot["battery_v"]
        if vbat and vbat < BATTERY_TAKEOFF_MIN_V:
            self._log(
                f"[GS] REFUSED takeoff: battery {vbat:.2f} V < "
                f"{BATTERY_TAKEOFF_MIN_V} V"
            )
            return
        if vbat and vbat < BATTERY_WARN_V:
            self._log(f"[GS] WARNING: battery {vbat:.2f} V is low")

        height = max(0.1, min(height, MAX_HEIGHT))
        self._reset_motor_overrides(cf)
        if not self._arm(cf):
            self._log("[GS] Takeoff aborted: arming failed")
            return

        self._flying = True
        self._set("flying", True)
        self._log(f"[GS] Takeoff -> {height:.2f} m")
        self._ramp(cf, 0.0, height, TAKEOFF_TIME)

    def _land(self, cf):
        if not self._flying:
            self._log("[GS] Land ignored: not flying")
            return
        z_est = self._snapshot["z"]
        z_start = self._z_hold
        if z_est and z_est > 0.05:
            z_start = z_est
        z_start = max(0.0, min(z_start, MAX_Z_HOLD))
        self._log(f"[GS] Landing from {z_start:.2f} m")
        self._ramp(cf, z_start, 0.0, LAND_TIME)
        self._settle(cf)
        self._cut(cf, reason="landed")

    def _hover(self, cf):
        if self._flying:
            self._last_move = time.monotonic()
            self._log("[GS] Hover (holding altitude)")

    def _move(self, cf, cmd):
        if not self._flying:
            self._log("[GS] Move ignored: not flying (takeoff first)")
            return
        vx = float(cmd.get("vx") or 0.0)
        vy = float(cmd.get("vy") or 0.0)
        vz = float(cmd.get("vz") or 0.0)
        yawrate = float(cmd.get("yawrate") or 0.0)
        vx = max(-0.5, min(0.5, vx))
        vy = max(-0.5, min(0.5, vy))
        vz = max(-0.5, min(0.5, vz))
        yawrate = max(-120.0, min(120.0, yawrate))

        self._last_move = time.monotonic()
        # Stream for a short window; the GUI/CLI refresh the command to
        # keep it alive (the watchdog hovers after MOVE_WATCHDOG_S).
        deadline = time.monotonic() + 0.2
        while (
            time.monotonic() < deadline
            and not self._stop.is_set()
            and not self._emergency_pending()
            and not self._link_stale()
        ):
            if vz:
                z = self._z_hold + vz * STEP
                self._z_hold = max(0.0, min(MAX_Z_HOLD, z))
            cf.commander.send_hover_setpoint(vx, vy, yawrate, self._z_hold)
            time.sleep(STEP)

    def _watchdog(self, cf):
        if self._flying and time.monotonic() - self._last_move > MOVE_WATCHDOG_S:
            self._log("[GS] Move watchdog expired -> hover")
            self._last_move = time.monotonic()
            cf.commander.send_hover_setpoint(0, 0, 0, self._z_hold)

    def _spin_test(self, cf, cmd):
        """Slow-spin each motor one at a time via the motorPowerSet params.

        Drone must be on a flat surface with propellers on.  Uses a low
        power (~6%) for a few seconds per motor.  The overrides are ALWAYS
        cleared in a finally block, and the urgent emergency channel is
        checked between motors and inside each spin, so E-STOP/X still
        works mid-test.
        """
        power = int(cmd.get("power", SPIN_POWER))
        duration = float(cmd.get("duration", SPIN_TIME))
        power = max(0, min(65535, power))
        duration = max(0.5, min(duration, 8.0))

        if self._flying:
            self._log("[GS] spin_test refused: drone is flying")
            return
        if self._estop_latched:
            self._log(
                "[GS] spin_test refused: E-STOP latched "
                "(power-cycle the drone to unlock)"
            )
            return
        self._log(
            f"[GS] Spin test: power={power} ({100 * power / 65535:.0f}%), "
            f"{duration:.0f}s per motor"
        )
        try:
            cf.param.set_value("motorPowerSet.enable", 1)
            time.sleep(0.3)
            for name in SPIN_MOTORS:
                if self._stop.is_set() or self._emergency_pending():
                    break
                self._log(f"[GS] Spinning {name} ... (按 X 或 E-STOP 停止)")
                cf.param.set_value(f"motorPowerSet.{name}", power)
                deadline = time.monotonic() + duration
                while (
                    time.monotonic() < deadline
                    and not self._stop.is_set()
                    and not self._emergency_pending()
                    and not self._link_stale()
                ):
                    time.sleep(0.05)
                try:
                    cf.param.set_value(f"motorPowerSet.{name}", 0)
                except Exception:
                    pass
        except Exception as exc:
            self._log(f"[GS] Spin test error: {exc}")
            self._log("[GS] 若报 motorPowerSet 参数不存在，请删除 groundstation/cache 后重试")
        finally:
            for name in SPIN_MOTORS:
                try:
                    cf.param.set_value(f"motorPowerSet.{name}", 0)
                except Exception:
                    pass
            try:
                cf.param.set_value("motorPowerSet.enable", 0)
            except Exception:
                pass
            self._log("[GS] Spin test done, motor overrides cleared")

    # ------------------------------------------------------------------ #
    # Low-level helpers
    # ------------------------------------------------------------------ #

    def _ramp(self, cf, z0, z1, duration):
        steps = int(duration * RATE)
        for i in range(1, steps + 1):
            if (
                self._stop.is_set()
                or self._emergency_pending()
                or self._link_stale()
            ):
                break
            z = z0 + (z1 - z0) * i / steps
            self._z_hold = z
            cf.commander.send_hover_setpoint(0, 0, 0, z)
            time.sleep(STEP)

    def _settle(self, cf, duration=SETTLE_TIME):
        deadline = time.monotonic() + duration
        while (
            time.monotonic() < deadline
            and not self._stop.is_set()
            and not self._emergency_pending()
            and not self._link_stale()
        ):
            self._z_hold = 0.0
            cf.commander.send_hover_setpoint(0, 0, 0, 0)
            time.sleep(STEP)

    def _cut(self, cf, reason="stop"):
        """Immediately stop setpoints and disarm (motors cut at once)."""
        try:
            cf.commander.send_stop_setpoint()
        except Exception:
            pass
        try:
            cf.commander.send_notify_setpoint_stop()
        except Exception:
            pass
        self._disarm(cf)
        self._flying = False
        self._armed = False
        self._set("flying", False)
        self._set("armed", False)
        self._log(f"[GS] Motors cut ({reason})")

    def _arm(self, cf):
        try:
            cf.param.set_value("system.arm", 1)
        except Exception as exc:
            self._log(f"[GS] Arm parameter error: {exc}")
            return False
        time.sleep(0.3)
        try:
            return str(cf.param.get_value("system.arm")) == "1"
        except Exception:
            return False

    def _disarm(self, cf):
        try:
            cf.param.set_value("system.arm", 0)
        except Exception:
            pass

    def _reset_motor_overrides(self, cf):
        try:
            cf.param.set_value("motorPowerSet.enable", 0)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Telemetry
    # ------------------------------------------------------------------ #

    def _setup_logging(self, cf):
        pos = LogConfig(name="GS-Position", period_in_ms=100)
        pos.add_variable("stateEstimate.x", "float")
        pos.add_variable("stateEstimate.y", "float")
        pos.add_variable("stateEstimate.z", "float")
        pos.data_received_cb.add_callback(self._on_position)
        cf.log.add_config(pos)
        pos.start()

        att = LogConfig(name="GS-Attitude", period_in_ms=100)
        att.add_variable("stabilizer.roll", "float")
        att.add_variable("stabilizer.pitch", "float")
        att.add_variable("stabilizer.yaw", "float")
        att.data_received_cb.add_callback(self._on_attitude)
        cf.log.add_config(att)
        att.start()

        batt = LogConfig(name="GS-Battery", period_in_ms=1000)
        batt.add_variable("pm.vbat", "FP16")
        batt.data_received_cb.add_callback(self._on_battery)
        cf.log.add_config(batt)
        batt.start()

        sup = LogConfig(name="GS-Supervisor", period_in_ms=100)
        sup.add_variable("supervisor.info", "uint16_t")
        sup.data_received_cb.add_callback(self._on_supervisor)
        cf.log.add_config(sup)
        sup.start()

        try:
            link = LogConfig(name="GS-Link", period_in_ms=200)
            link.add_variable("crtp.link_quality", "uint8_t")
            link.data_received_cb.add_callback(self._on_link)
            cf.log.add_config(link)
            link.start()
        except Exception:
            pass  # link_quality is unavailable on some firmwares

    def _on_position(self, ts, data, logconf):
        with self._lock:
            s = self._snapshot
            s["x"] = data.get("stateEstimate.x", s["x"])
            s["y"] = data.get("stateEstimate.y", s["y"])
            s["z"] = data.get("stateEstimate.z", s["z"])
            s["last_update"] = time.time()

    def _on_attitude(self, ts, data, logconf):
        with self._lock:
            s = self._snapshot
            s["roll"] = data.get("stabilizer.roll", s["roll"])
            s["pitch"] = data.get("stabilizer.pitch", s["pitch"])
            s["yaw"] = data.get("stabilizer.yaw", s["yaw"])

    def _on_battery(self, ts, data, logconf):
        with self._lock:
            self._snapshot["battery_v"] = data.get("pm.vbat", 0.0)

    def _on_supervisor(self, ts, data, logconf):
        info = data.get("supervisor.info", 0)
        with self._lock:
            self._snapshot["supervisor_info"] = info
            self._snapshot["locked"] = bool(info & LOCKED_BIT)

    def _on_link(self, ts, data, logconf):
        with self._lock:
            self._snapshot["link_quality"] = data.get("crtp.link_quality", 0.0)

    # ------------------------------------------------------------------ #
    # E-STOP latch: once estop fires, takeoff/spin are refused until the
    # drone is power-cycled.  A "restart" is only accepted when the link
    # went fully offline and a new connection is established after the
    # drone was unreachable for ESTOP_UNLOCK_OFFLINE_S seconds, so radio
    # blips never clear the latch.  The latch survives ground station
    # restarts via cache/estop_latch.json.
    # ------------------------------------------------------------------ #

    def _set_estop_latch(self, latched):
        with self._lock:
            self._estop_latched = bool(latched)
            self._snapshot["estop_latched"] = self._estop_latched
            connected = self._snapshot["connected"]
        if latched:
            if self._offline_since is None and not connected:
                self._offline_since = time.time()
            self._persist_estop_latch()
            self._log(
                "[GS] E-STOP latched — takeoff/spin refused until drone restart"
            )
        else:
            self._offline_since = None
            self._persist_estop_latch(clear=True)
            self._log("[GS] E-STOP latch cleared")

    def _maybe_clear_estop_latch(self):
        if not self._estop_latched:
            return
        if self._offline_since is not None and (
            time.time() - self._offline_since >= ESTOP_UNLOCK_OFFLINE_S
        ):
            self._set_estop_latch(False)
            self._log("[GS] Drone restart confirmed (offline >= threshold) — unlocked")
        else:
            self._log(
                "[GS] Link reconnected but restart not confirmed — E-STOP latch stays"
            )

    def _persist_estop_latch(self, clear=False):
        path = os.path.join(self._cache_dir, "estop_latch.json")
        try:
            if clear:
                if os.path.exists(path):
                    os.remove(path)
                return
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "latched": True,
                        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "offline_since": self._offline_since,
                    },
                    fh,
                )
        except Exception as exc:
            self._log(f"[GS] E-STOP latch persistence failed: {exc}")

    def _load_estop_latch(self):
        path = os.path.join(self._cache_dir, "estop_latch.json")
        try:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("latched"):
                self._estop_latched = True
                self._snapshot["estop_latched"] = True
                # A fresh offline -> reconnect cycle must be observed by
                # this process before unlocking; stale timestamps from a
                # previous session never count.
                self._offline_since = None
                self._log("[GS] E-STOP latch restored from previous session")
        except Exception as exc:
            self._log(f"[GS] E-STOP latch load failed: {exc}")

    def _set(self, key, value):
        with self._lock:
            self._snapshot[key] = value

    def _log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        try:
            self._log_lines.put_nowait(line)
        except queue.Full:
            try:
                self._log_lines.get_nowait()
            except queue.Empty:
                pass
            try:
                self._log_lines.put_nowait(line)
            except queue.Full:
                pass
