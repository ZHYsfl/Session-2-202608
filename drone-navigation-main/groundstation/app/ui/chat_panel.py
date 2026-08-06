"""OpenClaw chat panel: talk to the local OpenClaw gateway from the GUI."""

import json
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_HISTORY = 20


class ChatPanel(QWidget):
    def __init__(self, chat, controller, system_prompt="", parent=None):
        super().__init__(parent)
        self._chat = chat
        self._ctrl = controller
        self._system_prompt = system_prompt
        self._history = []
        self._busy = False

        self._build_ui()
        self._check_health()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)

        self._lbl_status = QLabel("OpenClaw: 检测中 ...")
        self._lbl_status.setStyleSheet("color: #889; font-size: 13px;")
        root.addWidget(self._lbl_status)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(2000)
        self._view.setStyleSheet(
            "font-family: monospace; font-size: 14px; "
            "background: #0d1117; color: #e6edf3;"
        )
        self._view.appendPlainText("可以在聊天里直接指挥 OpenClaw 操作无人机。")
        root.addWidget(self._view, stretch=1)

        row = QHBoxLayout()
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(
            "例如：检查无人机状态，然后起飞到 0.4 米悬停"
        )
        self._edit.returnPressed.connect(self._send)
        self._chk_telemetry = QCheckBox("附带遥测")
        self._chk_telemetry.setChecked(True)
        self._btn_send = QPushButton("发送")
        self._btn_stop = QPushButton("停止")
        self._btn_clear = QPushButton("清空")
        row.addWidget(self._edit, stretch=1)
        row.addWidget(self._chk_telemetry)
        row.addWidget(self._btn_send)
        row.addWidget(self._btn_stop)
        row.addWidget(self._btn_clear)
        root.addLayout(row)

        self._btn_send.clicked.connect(self._send)
        self._btn_stop.clicked.connect(self._stop_request)
        self._btn_clear.clicked.connect(self._clear)
        self._update_busy(False)

    # ------------------------------------------------------------------ #

    def _check_health(self):
        ok = self._chat.health()
        if ok:
            self._lbl_status.setText(f"OpenClaw: 在线 ({self._chat.base_url})")
            self._lbl_status.setStyleSheet("color: #2ecc71;")
        else:
            self._lbl_status.setText(
                f"OpenClaw: 未连接 ({self._chat.base_url}) — 检查 gateway 是否在运行"
            )
            self._lbl_status.setStyleSheet("color: #e74c3c;")

    def _send(self):
        text = self._edit.text().strip()
        if not text or self._busy:
            return
        self._edit.clear()
        self._append("你", text)
        self._history.append({"role": "user", "content": text})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        if self._chk_telemetry.isChecked():
            snap = self._ctrl.snapshot()
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前无人机遥测快照: "
                        + json.dumps(snap, ensure_ascii=False)
                    ),
                }
            )
        messages += self._history

        self._view.appendPlainText("")
        self._update_busy(True)
        self._lbl_status.setText("OpenClaw: 思考中 ...")
        self._chat.start_request(messages)

    def _drain(self):
        for ev in self._chat.drain():
            t = ev.get("type")
            if t == "delta":
                self._view.insertPlainText(ev.get("text", ""))
            elif t == "tool":
                self._view.appendPlainText(
                    f"\n  [工具调用] {ev.get('name')} args={ev.get('args', '')}"
                )
            elif t == "error":
                self._view.appendPlainText(f"\n[错误] {ev.get('text', '')}")
                self._lbl_status.setText("OpenClaw: 请求失败")
                self._lbl_status.setStyleSheet("color: #e74c3c;")
                self._update_busy(False)
            elif t == "done":
                self._lbl_status.setText(f"OpenClaw: 在线 ({self._chat.base_url})")
                self._lbl_status.setStyleSheet("color: #2ecc71;")
                self._update_busy(False)

    def _stop_request(self):
        self._chat.cancel()
        self._lbl_status.setText("OpenClaw: 已停止")
        self._update_busy(False)

    def _clear(self):
        self._chat.cancel()
        self._view.clear()
        self._history.clear()
        self._update_busy(False)

    def _append(self, who, text):
        self._view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {who}: {text}")

    def _update_busy(self, busy):
        self._busy = busy
        self._btn_send.setEnabled(not busy)
        self._btn_stop.setEnabled(busy)

    def shutdown(self):
        self._timer.stop()
        self._chat.cancel()
