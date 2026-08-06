"""Background monitoring tasks for the ground station.

The monitor thread periodically runs a detection (e.g. red blocks) on the
latest camera frame and pushes a WeChat message only when something is
found.  It also watches the battery and sleeps automatically below a
threshold, so a long-running patrol can't drain the drone.

Delivery uses the OpenClaw CLI:
    openclaw message send --channel openclaw-weixin --target <id>
        --message ... --media <file>
"""

import glob
import json
import os
import subprocess
import tempfile
import threading
import time

OPENCLAW_BIN = os.path.expanduser("~/node-v22.23.2-linux-x64/bin/openclaw")
NODE_BIN = os.path.expanduser("~/node-v22.23.2-linux-x64/bin")


def _latest_wechat_target():
    """Best-effort: parse the most recent WeChat sender id from OpenClaw logs."""
    try:
        logs = sorted(glob.glob("/tmp/openclaw/openclaw-*.log"), reverse=True)
        for log in logs:
            for line in reversed(open(log, "r", errors="replace").read().splitlines()):
                if "@im.wechat" in line and "config cached" in line:
                    start = line.find("config cached for ")
                    if start < 0:
                        continue
                    tail = line[start + len("config cached for ") :]
                    token = tail.split('"')[0].strip()
                    if token.endswith("@im.wechat"):
                        return token
    except Exception:
        pass
    return None


class MonitorRunner:
    def __init__(self, detector, video, controller, wechat_target=None):
        self._detector = detector
        self._video = video
        self._controller = controller
        self._wechat_target = wechat_target
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {
            "running": False,
            "interval": 30,
            "color": "red",
            "battery_threshold": 3.7,
            "target": wechat_target or "",
            "last_check": None,
            "last_result": None,
            "stopped_reason": None,
        }

    # ------------------------------------------------------------------ #

    def start(self, interval=30, color="red", target=None, battery_threshold=3.7):
        self.stop(reason="restart")
        target = target or self._wechat_target or _latest_wechat_target()
        if not target:
            return {
                "ok": False,
                "error": "no WeChat target (pass target= or set monitor.wechat_target)",
            }
        interval = max(5, int(interval))
        battery_threshold = max(3.0, min(4.2, float(battery_threshold)))
        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "interval": interval,
                    "color": color,
                    "battery_threshold": battery_threshold,
                    "target": target,
                    "last_check": None,
                    "last_result": None,
                    "stopped_reason": None,
                }
            )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval, color, target, battery_threshold),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "status": self.status()}

    def stop(self, reason=None):
        self._stop.set()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=3)
        self._thread = None
        with self._lock:
            self._status["running"] = False
            self._status["stopped_reason"] = reason
        return {"ok": True}

    def status(self):
        with self._lock:
            return dict(self._status)

    # ------------------------------------------------------------------ #

    def _loop(self, interval, color, target, battery_threshold):
        while not self._stop.is_set():
            snap = self._controller.snapshot()
            vbat = snap.get("battery_v")
            if vbat is not None and vbat and vbat < battery_threshold:
                self.stop(reason=f"battery low ({vbat:.2f}V < {battery_threshold}V)")
                self._send(
                    target,
                    f"无人机电量 {vbat:.2f}V，低于 {battery_threshold}V，监控已自动休眠。",
                )
                return

            frame = self._video.latest() if self._video else None
            result = None
            if frame and self._detector is not None:
                try:
                    result = self._detector.detect_color(frame, color=color)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}

            now = time.strftime("%H:%M:%S")
            with self._lock:
                self._status["last_check"] = now
                self._status["last_result"] = (
                    None if result is None else result.get("error")
                )

            count = result.get("count", 0) if result else 0
            if count > 0:
                annotated = result.get("annotated_jpeg")
                media_path = None
                if annotated:
                    media_path = os.path.join(
                        tempfile.gettempdir(),
                        f"gs_monitor_{int(time.time() * 1000)}.jpg",
                    )
                    with open(media_path, "wb") as fh:
                        fh.write(annotated)
                self._send(
                    target,
                    f"[监控] {now} 检测到 {count} 个{color}物块"
                    + ("（见图片）" if media_path else ""),
                    media=media_path,
                )
                with self._lock:
                    self._status["last_result"] = (
                        f"found {count} {color} at {now}"
                    )

            # Sleep in small steps so stop() responds promptly.
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline and not self._stop.is_set():
                time.sleep(0.5)

    def _send(self, target, message, media=None):
        cmd = [
            OPENCLAW_BIN,
            "message",
            "send",
            "--channel",
            "openclaw-weixin",
            "--target",
            target,
            "--message",
            message,
        ]
        if media:
            cmd += ["--media", media]
        env = dict(os.environ)
        env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {"ok": proc.returncode == 0, "stderr": proc.stderr[-300:]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
