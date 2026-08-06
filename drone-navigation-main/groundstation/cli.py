#!/usr/bin/env python3
"""Headless command-line interface for the Crazyflie ground station.

Runs the exact same CrazyflieController as the GUI, but without a window.
This is the primary interface OpenClaw (or a script) uses to operate the
drone:

  python cli.py status
  python cli.py takeoff --height 0.4
  python cli.py move --vx 0.3 --duration 1.5
  python cli.py land
  python cli.py estop
  python cli.py serve          # long-running local HTTP API (default port 18790)
"""

import argparse
import json
import sys
import time

from app.command_server import CommandServer
from app.config import load_config
from app.controller import CrazyflieController


def _out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def _connect(controller, timeout=20.0):
    controller.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.snapshot()["connected"]:
            return True
        time.sleep(0.2)
    return False


def _finish(controller):
    controller.request("stop")
    controller.stop()


def cmd_status(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    if args.watch:
        ctrl.start()
        try:
            while True:
                _out(ctrl.snapshot())
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            ctrl.stop()
        return 0
    if not _connect(ctrl, timeout=args.timeout):
        _out({"error": "connect timeout", "status": ctrl.snapshot()})
        return 1
    time.sleep(1.0)
    _out(ctrl.snapshot())
    _finish(ctrl)
    return 0


def _wait_until(ctrl, key, value, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ctrl.snapshot().get(key) == value:
            return True
        time.sleep(0.1)
    return False


def cmd_takeoff(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    if not _connect(ctrl, timeout=args.timeout):
        _out({"error": "connect timeout", "status": ctrl.snapshot()})
        return 1
    snap = ctrl.snapshot()
    if snap["locked"]:
        _out({"error": "drone is LOCKED (power-cycle required)", "status": snap})
        _finish(ctrl)
        return 1
    if snap["battery_v"] and snap["battery_v"] < 3.7:
        _out({"error": "battery too low", "battery_v": snap["battery_v"]})
        _finish(ctrl)
        return 1
    ctrl.request("takeoff", height=args.height)
    ok = _wait_until(ctrl, "flying", True, timeout=8.0)
    _out({"takeoff": "requested", "flying": ok, "status": ctrl.snapshot()})
    if ok:
        # Keep the process alive while the ramp completes so the radio
        # link is not dropped mid-takeoff.
        time.sleep(args.takeoff_time)
        _out(ctrl.snapshot())
    _finish(ctrl)
    return 0 if ok else 1


def cmd_land(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    if not _connect(ctrl, timeout=args.timeout):
        _out({"error": "connect timeout", "status": ctrl.snapshot()})
        return 1
    ctrl.request("land")
    ok = _wait_until(ctrl, "flying", False, timeout=12.0)
    _out({"land": "requested", "landed": ok, "status": ctrl.snapshot()})
    _finish(ctrl)
    return 0 if ok else 1


def cmd_move(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    if not _connect(ctrl, timeout=args.timeout):
        _out({"error": "connect timeout", "status": ctrl.snapshot()})
        return 1
    ctrl.request(
        "move",
        vx=args.vx,
        vy=args.vy,
        vz=args.vz,
        yawrate=args.yawrate,
        duration=args.duration,
    )
    time.sleep(args.duration + 0.5)
    _out({"move": "done", "status": ctrl.snapshot()})
    _finish(ctrl)
    return 0


def cmd_simple(action):
    def _run(args, cfg):
        ctrl = CrazyflieController(cfg["radio_uri"])
        if not _connect(ctrl, timeout=args.timeout):
            _out({"error": "connect timeout", "status": ctrl.snapshot()})
            return 1
        ctrl.request(action)
        time.sleep(0.4)
        _out({action: "requested", "status": ctrl.snapshot()})
        _finish(ctrl)
        return 0

    return _run


def cmd_spin(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    if not _connect(ctrl, timeout=args.timeout):
        _out({"error": "connect timeout", "status": ctrl.snapshot()})
        return 1
    ctrl.request("spin_test", power=args.power, duration=args.duration)
    # 4 motors, each spinning for `duration` seconds + settle margin
    time.sleep(args.duration * 4 + 1.5)
    _out({"spin_test": "done", "status": ctrl.snapshot()})
    _finish(ctrl)
    return 0


def cmd_serve(args, cfg):
    ctrl = CrazyflieController(cfg["radio_uri"])
    ctrl.start()
    server = CommandServer(
        ctrl,
        host=cfg.get("command_server_host", "127.0.0.1"),
        port=args.port or cfg.get("command_server_port", 18790),
        token=cfg.get("command_server_token") or None,
    )
    server.start()
    print(f"[GS] HTTP command API: http://127.0.0.1:{server.port}")
    print("[GS] Endpoints: GET /health, GET /status, POST /command")
    print("[GS] Ctrl+C 停止")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        ctrl.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Crazyflie ground station (headless CLI)"
    )
    parser.add_argument("--uri", help="radio URI override")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="print telemetry snapshot")
    p_status.add_argument("--watch", action="store_true", help="stream every 1 s")
    p_status.add_argument("--timeout", type=float, default=20.0)

    p_takeoff = sub.add_parser("takeoff", help="take off and hover")
    p_takeoff.add_argument("--height", type=float, default=0.3)
    p_takeoff.add_argument("--timeout", type=float, default=20.0)
    p_takeoff.add_argument("--takeoff-time", type=float, default=3.5)

    p_land = sub.add_parser("land", help="controlled landing")
    p_land.add_argument("--timeout", type=float, default=20.0)

    p_hover = sub.add_parser("hover", help="hold altitude, stop drifting")
    p_hover.add_argument("--timeout", type=float, default=20.0)

    p_stop = sub.add_parser("stop", help="cut motors immediately")
    p_stop.add_argument("--timeout", type=float, default=20.0)

    p_estop = sub.add_parser("estop", help="EMERGENCY motor cut")
    p_estop.add_argument("--timeout", type=float, default=20.0)

    p_move = sub.add_parser("move", help="velocity move for a duration")
    p_move.add_argument("--vx", type=float, default=0.0)
    p_move.add_argument("--vy", type=float, default=0.0)
    p_move.add_argument("--vz", type=float, default=0.0)
    p_move.add_argument("--yawrate", type=float, default=0.0)
    p_move.add_argument("--duration", type=float, default=1.0)
    p_move.add_argument("--timeout", type=float, default=20.0)

    p_serve = sub.add_parser("serve", help="long-running HTTP command API")
    p_serve.add_argument("--port", type=int, default=None)

    p_spin = sub.add_parser(
        "spin-test", help="slow-spin each motor one by one (bench check)"
    )
    p_spin.add_argument("--power", type=int, default=4000)
    p_spin.add_argument("--duration", type=float, default=2.0)
    p_spin.add_argument("--timeout", type=float, default=20.0)

    args = parser.parse_args(argv)
    cfg = load_config()
    if args.uri:
        cfg["radio_uri"] = args.uri

    handlers = {
        "status": cmd_status,
        "takeoff": cmd_takeoff,
        "land": cmd_land,
        "move": cmd_move,
        "hover": cmd_simple("hover"),
        "stop": cmd_simple("stop"),
        "estop": cmd_simple("estop"),
        "serve": cmd_serve,
        "spin-test": cmd_spin,
    }
    return handlers[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
