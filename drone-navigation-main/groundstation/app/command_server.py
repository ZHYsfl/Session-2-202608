"""Local HTTP command API so OpenClaw (or any local tool) can operate the
drone without the GUI.

Endpoints (all JSON, bound to 127.0.0.1 only):
    GET  /health   -> {"ok": true, "service": "groundstation", "actions": [...]}
    GET  /status   -> telemetry + state snapshot
    POST /command  -> {"action": "takeoff", "height": 0.3}

If config["command_server_token"] is set, every request must carry
`Authorization: Bearer <token>` or `?token=<token>`.
"""

import json
import threading
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
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
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


class CommandServer:
    """Thin wrapper around a threaded HTTP server."""

    def __init__(self, controller, host="127.0.0.1", port=18790, token=None):
        self.controller = controller
        self.host = host
        self.port = port
        self.token = token
        self._httpd = None
        self._thread = None

    def start(self):
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.controller = self.controller
        self._httpd.token = self.token
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
