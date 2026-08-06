"""Minimal OpenAI-compatible chat client for the local OpenClaw gateway.

Talks to the gateway's Chat Completions endpoint (requires
``gateway.http.endpoints.chatCompletions.enabled = true`` in
~/.openclaw/openclaw.json).  Streaming SSE responses are parsed on a
background thread and delivered as events to a thread-safe queue; the GUI
drains the queue with a timer.

The client also implements the *client-side tool loop* supported by the
gateway's chat tool contract: when the agent emits ``tool_calls``, the
ground station executes them locally through ``tool_executor`` and feeds
the JSON results back as ``role: "tool"`` messages, until the agent
produces a final plain-text answer.

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

MAX_TOOL_ROUNDS = 8


class OpenClawChat:
    def __init__(
        self,
        base_url="http://127.0.0.1:18789",
        token="",
        model="openclaw/default",
        user="groundstation-gui",
        timeout=120,
        tools=None,
        tool_executor=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model
        self.user = user
        self.timeout = timeout
        self.tools = tools or []
        self.tool_executor = tool_executor
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
        try:
            msgs = list(messages)
            for _round in range(MAX_TOOL_ROUNDS + 1):
                if self._cancel.is_set():
                    break
                content, tool_calls = self._round_trip(msgs)
                if content:
                    self._events.put({"type": "delta", "text": content})
                if not tool_calls:
                    break
                if self.tool_executor is None:
                    self._events.put(
                        {
                            "type": "error",
                            "text": "agent requested tools but no executor is configured",
                        }
                    )
                    break
                msgs.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                for tc in tool_calls:
                    try:
                        result = self.tool_executor(tc["name"], tc["args"])
                    except Exception as exc:  # never kill the loop on tool bugs
                        result = json.dumps(
                            {"ok": False, "message": f"tool crashed: {exc}"},
                            ensure_ascii=False,
                        )
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
            else:
                self._events.put(
                    {
                        "type": "error",
                        "text": f"tool loop exceeded {MAX_TOOL_ROUNDS} rounds",
                    }
                )
        except Exception as exc:
            self._events.put({"type": "error", "text": str(exc)})
        finally:
            self._events.put({"type": "done"})

    def _round_trip(self, messages):
        """One chat round.  Returns (content, tool_calls)."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "user": self.user,
        }
        if self.tools:
            payload["tools"] = self.tools
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)

        content_parts = []
        calls = {}
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            buf = b""
            while not self._cancel.is_set():
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    idx = buf.find(b"\n\n")
                    if idx < 0:
                        break
                    block = buf[:idx]
                    buf = buf[idx + 2 :]
                    text, tc = self._parse_block(
                        block.decode("utf-8", "replace"), calls
                    )
                    if text:
                        content_parts.append(text)
        tool_calls = []
        for entry in calls.values():
            try:
                entry["args"] = json.loads(entry["arguments"] or "{}")
            except json.JSONDecodeError:
                entry["args"] = {}
            tool_calls.append(entry)
        return "".join(content_parts), tool_calls

    def _parse_block(self, block, calls):
        """Parse one SSE block into (text_delta, new_tool_calls)."""
        text = None
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return text, None
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
                text = (text or "") + content
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                entry = calls.setdefault(
                    idx,
                    {
                        "id": tc.get("id") or f"call_{idx}",
                        "name": "",
                        "arguments": "",
                        "args": {},
                    },
                )
                fn = tc.get("function") or {}
                if fn.get("name"):
                    entry["name"] += fn["name"]
                if fn.get("arguments"):
                    entry["arguments"] += fn["arguments"]
        return text, None
