"""OpenClaw gateway log monitor panel.

Tails the gateway JSON logs (normally /tmp/openclaw/openclaw-*.log, with a
fallback to ~/openclaw.log) and shows a compact, filtered view of what the
agent is doing: model requests, tool calls, channel events and errors.
"""

import glob
import json
import os
import re
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_LOG_DIR = "/tmp/openclaw"
FALLBACK_LOG = os.path.expanduser("~/openclaw.log")
MAX_BLOCKS = 2000


class LogMonitorPanel(QWidget):
    def __init__(self, log_dir=DEFAULT_LOG_DIR, parent=None):
        super().__init__(parent)
        self._log_dir = log_dir
        self._path = None
        self._pos = 0
        self._paused = False

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)

        self._lbl_status = QLabel("OpenClaw 日志: 检测中 ...")
        self._lbl_status.setStyleSheet("color: #889; font-size: 13px;")
        root.addWidget(self._lbl_status)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_BLOCKS)
        self._view.setStyleSheet(
            "font-family: monospace; font-size: 12px; "
            "background: #0d1117; color: #c9d1d9;"
        )
        root.addWidget(self._view, stretch=1)

        row = QHBoxLayout()
        self._chk_filter = QCheckBox("精简模式（过滤模型请求噪音）")
        self._chk_filter.setChecked(True)
        self._btn_pause = QPushButton("暂停")
        self._btn_clear = QPushButton("清空")
        row.addWidget(self._chk_filter)
        row.addStretch(1)
        row.addWidget(self._btn_pause)
        row.addWidget(self._btn_clear)
        root.addLayout(row)

        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_clear.clicked.connect(self._view.clear)

    # ------------------------------------------------------------------ #

    def _log_path(self):
        try:
            logs = sorted(
                glob.glob(os.path.join(self._log_dir, "openclaw-*.log")),
                key=os.path.getmtime,
                reverse=True,
            )
            if logs:
                return logs[0]
        except Exception:
            pass
        return FALLBACK_LOG if os.path.exists(FALLBACK_LOG) else None

    def _refresh(self):
        if self._paused:
            return
        path = self._log_path()
        if not path:
            self._lbl_status.setText("OpenClaw 日志: 未找到日志文件")
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if path != self._path:
            self._path = path
            self._pos = max(0, size - 128 * 1024)  # start from recent tail
            self._lbl_status.setText(f"OpenClaw 日志: {path}")
        if size < self._pos:
            self._pos = 0
        if size == self._pos:
            return
        try:
            with open(path, "r", errors="replace") as fh:
                fh.seek(self._pos)
                data = fh.read()
                self._pos = fh.tell()
        except OSError:
            return
        for line in data.splitlines():
            text = self._format(line)
            if text:
                self._view.appendPlainText(text)

    def _format(self, line):
        line = line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return line[:200]
        if not isinstance(obj, dict):
            return line[:200]
        ts = ""
        tmatch = re.search(r"T(\d{2}:\d{2}:\d{2})", obj.get("time") or "")
        if tmatch:
            ts = tmatch.group(1)
        sub = (obj.get("_meta") or {}).get("subsystem") or ""
        msg = obj.get("message")
        if isinstance(msg, dict):
            msg = json.dumps(msg, ensure_ascii=False)[:220]
        msg = str(msg or "")[:220]

        # Compact mode: hide the noisy provider request/response pairs.
        if self._chk_filter.isChecked():
            if "provider-transport-fetch" in str(sub) or "model-fetch" in str(msg):
                if "start provider=" in msg:
                    return None
                if "response provider=" in msg:
                    elapsed = "?"
                    try:
                        elapsed = msg.split("elapsedMs=")[1].split()[0]
                    except Exception:
                        pass
                    return f"[{ts}] [模型] {elapsed}ms"
        return f"[{ts}] [{sub}] {msg}"

    def _toggle_pause(self):
        self._paused = not self._paused
        self._btn_pause.setText("继续" if self._paused else "暂停")

    def shutdown(self):
        self._timer.stop()
