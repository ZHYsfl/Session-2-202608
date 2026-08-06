"""Local HTTP command API so OpenClaw (or any local tool) can operate the
drone without the GUI.

Endpoints (all JSON, bound to 127.0.0.1 only):
    GET  /health   -> {"ok": true, "service": "groundstation", "actions": [...]}
    GET  /status   -> telemetry + state snapshot
    GET  /capture  -> latest camera frame as image/jpeg (requires video source)
    POST /command  -> {"action": "takeoff", "height": 0.3}
    POST /detect   -> YOLO person detection on the latest frame
    POST /detect_color -> color-based block detection (e.g. red) on latest frame
    POST /monitor/start -> start a periodic detection patrol (interval, color)
    POST /monitor/stop  -> stop the patrol
    GET  /monitor/status -> patrol state

If config["command_server_token"] is set, every request must carry
`Authorization: Bearer <token>` or `?token=<token>`.
"""

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ACTIONS = ("takeoff", "land", "hover", "stop", "estop", "move", "spin_test")


class _Handler(BaseHTTPRequestHandler):
    server_version = "CrazyflieGroundStation/0.1"

    # ------------------------------------------------------------------ #
    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        token = self.server.token
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {token}":
            return True
        query = parse_qs(urlparse(self.path).query)
        return query.get("token", [None])[0] == token

    def log_message(self, fmt, *args):
        pass  # keep the console clean; controller logs are enough

    # ------------------------------------------------------------------ #
    def do_GET(self):
        if self.path in ("/health", "/health/"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "groundstation",
                    "actions": list(ACTIONS),
                },
            )
            return
        if self.path in ("/status", "/status/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, self.server.controller.snapshot())
            return
        if self.path in ("/capture", "/capture/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            frame = self.server.video.latest() if self.server.video else None
            if not frame:
                self._send_json(
                    503, {"error": "no video frame available (camera offline?)"}
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)
            return
        if self.path in ("/monitor/status", "/monitor/status/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            if self.server.monitor is None:
                self._send_json(503, {"error": "monitor unavailable"})
                return
            self._send_json(200, self.server.monitor.status())
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path in ("/detect", "/detect/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_detect()
            return
        if self.path in ("/detect_color", "/detect_color/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_detect_color()
            return
        if self.path in ("/monitor/start", "/monitor/start/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_monitor_start()
            return
        if self.path in ("/monitor/stop", "/monitor/stop/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_monitor_stop()
            return
        if self.path not in ("/command", "/command/"):
            self._send_json(404, {"error": "not found"})
            return
        if not self._authed():
            self._send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        action = payload.get("action")
        if action not in ACTIONS:
            self._send_json(
                400, {"error": f"unknown action (allowed: {', '.join(ACTIONS)})"}
            )
            return
        kwargs = {k: v for k, v in payload.items() if k != "action"}
        self.server.controller.request(action, **kwargs)
        self._send_json(
            202,
            {"ok": True, "action": action, "status": self.server.controller.snapshot()},
        )

    def _handle_detect(self):
        if self.server.detector is None or not self.server.detector.available():
            self._send_json(
                503,
                {"error": "YOLO detector unavailable (model missing?)"},
            )
            return
        frame = self.server.video.latest() if self.server.video else None
        if not frame:
            self._send_json(503, {"error": "no video frame available"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            conf = float(payload.get("conf", 0.4)) if isinstance(payload, dict) else 0.4
        except Exception:
            conf = 0.4
        try:
            res = self.server.detector.detect(frame, conf=conf)
        except Exception as exc:
            self._send_json(500, {"error": f"detection failed: {exc}"})
            return
        if not res.get("ok"):
            self._send_json(500, {"error": res.get("error", "detection failed")})
            return
        annotated = res.get("annotated_jpeg")
        annotated_path = None
        if annotated:
            annotated_path = os.path.join(
                tempfile.gettempdir(),
                f"gs_detect_{int(time.time() * 1000)}.jpg",
            )
            with open(annotated_path, "wb") as fh:
                fh.write(annotated)
        self._send_json(
            200,
            {
                "ok": True,
                "count": res["count"],
                "persons": res["persons"],
                "annotated_path": annotated_path,
            },
        )

    def _handle_detect_color(self):
        if self.server.detector is None:
            self._send_json(503, {"error": "detector unavailable"})
            return
        frame = self.server.video.latest() if self.server.video else None
        if not frame:
            self._send_json(503, {"error": "no video frame available"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            color = payload.get("color", "red") if isinstance(payload, dict) else "red"
            min_area_ratio = (
                float(payload.get("min_area_ratio", 0.005))
                if isinstance(payload, dict)
                else 0.005
            )
        except Exception:
            color, min_area_ratio = "red", 0.005
        try:
            res = self.server.detector.detect_color(
                frame, color=color, min_area_ratio=min_area_ratio
            )
        except Exception as exc:
            self._send_json(500, {"error": f"color detection failed: {exc}"})
            return
        if not res.get("ok"):
            self._send_json(500, {"error": res.get("error", "detection failed")})
            return
        annotated = res.get("annotated_jpeg")
        annotated_path = None
        if annotated:
            annotated_path = os.path.join(
                tempfile.gettempdir(),
                f"gs_color_{int(time.time() * 1000)}.jpg",
            )
            with open(annotated_path, "wb") as fh:
                fh.write(annotated)
        self._send_json(
            200,
            {
                "ok": True,
                "color": res["color"],
                "count": res["count"],
                "regions": res["regions"],
                "annotated_path": annotated_path,
            },
        )

    def _handle_monitor_start(self):
        if self.server.monitor is None:
            self._send_json(503, {"error": "monitor unavailable"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            payload = payload if isinstance(payload, dict) else {}
        except Exception:
            payload = {}
        res = self.server.monitor.start(
            interval=payload.get("interval", 30),
            color=payload.get("color", "red"),
            target=payload.get("target"),
            battery_threshold=payload.get("battery_threshold", 3.7),
        )
        code = 200 if res.get("ok") else 400
        self._send_json(code, res)

    def _handle_monitor_stop(self):
        if self.server.monitor is None:
            self._send_json(503, {"error": "monitor unavailable"})
            return
        reason = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            reason = payload.get("reason") if isinstance(payload, dict) else None
        except Exception:
            pass
        self._send_json(200, self.server.monitor.stop(reason=reason))

    def _handle_monitor_status(self):
        if self.server.monitor is None:
            self._send_json(503, {"error": "monitor unavailable"})
            return
        self._send_json(200, self.server.monitor.status())


class CommandServer:
    """Thin wrapper around a threaded HTTP server."""

    def __init__(
        self,
        controller,
        host="127.0.0.1",
        port=18790,
        token=None,
        video=None,
        detector=None,
        monitor=None,
    ):
        self.controller = controller
        self.host = host
        self.port = port
        self.token = token
        self.video = video
        self.detector = detector
        self.monitor = monitor
        self._httpd = None
        self._thread = None

    def start(self):
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.controller = self.controller
        self._httpd.token = self.token
        self._httpd.video = self.video
        self._httpd.detector = self.detector
        self._httpd.monitor = self.monitor
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
