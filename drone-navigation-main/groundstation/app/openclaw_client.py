"""Minimal OpenAI-compatible chat client for the local OpenClaw gateway.

Talks to the gateway's Chat Completions endpoint (requires
``gateway.http.endpoints.chatCompletions.enabled = true`` in
~/.openclaw/openclaw.json).  Streaming SSE responses are parsed on a
background thread and delivered as events to a thread-safe queue; the GUI
drains the queue with a timer.

Event dicts:
    {"type": "delta", "text": "..."}   streamed assistant text
    {"type": "tool",  "name": ..., "args": ...}   client tool call
    {"type": "error", "text": "..."}
    {"type": "done"}
"""

import json
import queue
import threading
import urllib.request


class OpenClawChat:
    def __init__(
        self,
        base_url="http://127.0.0.1:18789",
        token="",
        model="openclaw/default",
        user="groundstation-gui",
        timeout=120,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model
        self.user = user
        self.timeout = timeout
        self._events = queue.Queue()
        self._cancel = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def health(self):
        """Ping the gateway (no auth needed for /health)."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_request(self, messages):
        """Start an async streaming chat request."""
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(list(messages),), daemon=True
        )
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def drain(self):
        """Return and clear all pending events."""
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        return out

    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _run(self, messages):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "user": self.user,
        }
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                buf = b""
                while not self._cancel.is_set():
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    # Consume complete SSE blocks (separated by a blank line)
                    while True:
                        idx = buf.find(b"\n\n")
                        if idx < 0:
                            break
                        block = buf[:idx]
                        buf = buf[idx + 2 :]
                        self._parse_event(block.decode("utf-8", "replace"))
        except Exception as exc:
            self._events.put({"type": "error", "text": str(exc)})
        finally:
            self._events.put({"type": "done"})

    def _parse_event(self, block):
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                self._events.put({"type": "delta", "text": content})
            for tc in delta.get("tool_calls") or []:
                fn = tc.get("function") or {}
                self._events.put(
                    {
                        "type": "tool",
                        "name": fn.get("name", ""),
                        "args": fn.get("arguments", ""),
                    }
                )
