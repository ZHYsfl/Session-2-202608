"""Main QT window: video, telemetry, attitude, and flight controls."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.chat_panel import ChatPanel
from app.ui.attitude_widget import AttitudeWidget
from app.ui.trajectory_widget import TrajectoryWidget

MOVE_XY = 0.3      # m/s, horizontal velocity per key/button
MOVE_Z = 0.2       # m/s, vertical velocity
MOVE_YAW = 40.0    # deg/s


class MainWindow(QMainWindow):
    def __init__(self, controller, video, cfg, chat=None):
        super().__init__()
        self._ctrl = controller
        self._video = video
        self._cfg = cfg
        self._chat = chat
        self._active = {"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw": 0.0}
        self._flash = False
        self._chat_panel = None

        self.setWindowTitle("Crazyflie 地面站 (standalone)")
        self.resize(1560, 960)
        self.setFocusPolicy(Qt.StrongFocus)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._move_timer = QTimer(self)
        self._move_timer.setInterval(150)
        self._move_timer.timeout.connect(self._apply_input)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        top = QWidget()
        root = QHBoxLayout(top)
        root.setContentsMargins(6, 6, 6, 6)

        root.addWidget(self._build_video_panel(), stretch=3)
        root.addWidget(self._build_telemetry_panel(), stretch=2)
        root.addWidget(self._build_control_panel(), stretch=2)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top)
        if self._chat is not None:
            oc = self._cfg.get("openclaw", {}) or {}
            self._chat_panel = ChatPanel(
                self._chat,
                self._ctrl,
                system_prompt=oc.get("system_prompt", ""),
            )
            splitter.addWidget(self._chat_panel)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([560, 220])
        self.setCentralWidget(splitter)
        self._log("按 T 起飞 | L 降落 | H 悬停 | X 急停 | Esc 停止")
        self._log("W/S/A/D 或方向键平移，Space 上升，Shift 下降，Q/E 旋转")

    def _build_video_panel(self):
        box = QGroupBox("ESP32 摄像头")
        v = QVBoxLayout(box)

        self._lbl_video = QLabel("视频加载中 ...")
        self._lbl_video.setMinimumSize(500, 360)
        self._lbl_video.setAlignment(Qt.AlignCenter)
        self._lbl_video.setStyleSheet("background-color: #101418; color: #889;")
        v.addWidget(self._lbl_video, stretch=3)

        traj_row = QHBoxLayout()
        traj_row.addWidget(QLabel("位置轨迹"))
        btn_reset_traj = QPushButton("重置")
        btn_reset_traj.setFocusPolicy(Qt.NoFocus)
        btn_reset_traj.clicked.connect(lambda: self._traj.reset())
        traj_row.addWidget(btn_reset_traj)
        v.addLayout(traj_row)

        self._traj = TrajectoryWidget()
        v.addWidget(self._traj, stretch=2)

        url_row = QHBoxLayout()
        self._edit_url = QLineEdit(self._cfg.get("camera_url", ""))
        btn_url = QPushButton("连接")
        btn_url.setFocusPolicy(Qt.NoFocus)
        btn_url.clicked.connect(self._on_reconnect_video)
        url_row.addWidget(QLabel("地址"))
        url_row.addWidget(self._edit_url, stretch=1)
        url_row.addWidget(btn_url)
        v.addLayout(url_row)

        self._chk_flip = QCheckBox("画面翻转 180°")
        self._chk_flip.setFocusPolicy(Qt.NoFocus)
        v.addWidget(self._chk_flip)
        return box

    def _build_telemetry_panel(self):
        box = QGroupBox("遥测")
        v = QVBoxLayout(box)

        self._attitude = AttitudeWidget()
        v.addWidget(self._attitude, stretch=1)

        self._bar_battery = QProgressBar()
        self._bar_battery.setRange(300, 450)
        self._bar_battery.setFormat("电池 -- V")
        v.addWidget(self._bar_battery)
        self._bar_alt = QProgressBar()
        self._bar_alt.setRange(0, 200)
        self._bar_alt.setFormat("高度 -- m")
        v.addWidget(self._bar_alt)
        self._bar_link = QProgressBar()
        self._bar_link.setRange(0, 100)
        self._bar_link.setFormat("链路 -- %")
        v.addWidget(self._bar_link)

        self._lbl_status = QLabel("未连接")
        self._lbl_status.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #e74c3c;"
        )
        v.addWidget(self._lbl_status)

        grid = QGridLayout()
        self._lbl_battery = QLabel("--")
        self._lbl_link = QLabel("--")
        self._lbl_pos = QLabel("--")
        self._lbl_atti = QLabel("--")
        self._lbl_locked = QLabel("")
        grid.addWidget(QLabel("电池"), 0, 0)
        grid.addWidget(self._lbl_battery, 0, 1)
        grid.addWidget(QLabel("链路"), 0, 2)
        grid.addWidget(self._lbl_link, 0, 3)
        grid.addWidget(QLabel("位置 x/y/z"), 1, 0)
        grid.addWidget(self._lbl_pos, 1, 1, 1, 3)
        grid.addWidget(QLabel("姿态 R/P/Y"), 2, 0)
        grid.addWidget(self._lbl_atti, 2, 1, 1, 3)
        v.addLayout(grid)

        self._lbl_uri = QLabel(f"URI: {self._ctrl.uri}")
        self._lbl_uri.setStyleSheet("color: #667; font-size: 13px;")
        v.addWidget(self._lbl_uri)
        self._lbl_locked.setStyleSheet(
            "color: #e67e22; font-weight: bold; font-size: 15px;"
        )
        v.addWidget(self._lbl_locked)

        v.addWidget(QLabel("日志"))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setStyleSheet(
            "font-family: monospace; font-size: 14px; background: #0d1117; color: #c9d1d9;"
        )
        v.addWidget(self._log_view, stretch=1)
        return box

    def _build_control_panel(self):
        box = QGroupBox("飞行控制")
        v = QVBoxLayout(box)

        h = QHBoxLayout()
        h.addWidget(QLabel("起飞高度 (m)"))
        self._spin_height = QDoubleSpinBox()
        self._spin_height.setRange(0.1, 1.5)
        self._spin_height.setSingleStep(0.05)
        self._spin_height.setValue(float(self._cfg.get("takeoff_height", 0.3)))
        self._spin_height.setDecimals(2)
        self._spin_height.setFocusPolicy(Qt.NoFocus)
        h.addWidget(self._spin_height, stretch=1)
        v.addLayout(h)

        self._btn_takeoff = QPushButton("起飞 (T)")
        self._btn_takeoff.setStyleSheet(
            "background:#27ae60; color:white; font-weight:bold; padding:14px;"
        )
        self._btn_takeoff.clicked.connect(
            lambda: self._ctrl.request("takeoff", height=self._spin_height.value())
        )
        self._btn_land = QPushButton("降落 (L)")
        self._btn_land.setStyleSheet(
            "background:#2980b9; color:white; font-weight:bold; padding:14px;"
        )
        self._btn_land.clicked.connect(lambda: self._ctrl.request("land"))
        self._btn_hover = QPushButton("悬停 (H)")
        self._btn_hover.clicked.connect(lambda: self._ctrl.request("hover"))
        self._btn_stop = QPushButton("停止 (Esc)")
        self._btn_stop.setStyleSheet(
            "background:#e67e22; color:white; padding:14px;"
        )
        self._btn_stop.clicked.connect(lambda: self._ctrl.request("stop"))
        self._btn_estop = QPushButton("急停 E-STOP (X)")
        self._btn_estop.setStyleSheet(
            "background:#c0392b; color:white; font-weight:bold;"
            "font-size:24px; padding:22px; border-radius:8px;"
        )
        self._btn_estop.clicked.connect(
            lambda: self._ctrl.request("estop")
        )
        for b in (
            self._btn_takeoff,
            self._btn_land,
            self._btn_hover,
            self._btn_stop,
            self._btn_estop,
        ):
            b.setFocusPolicy(Qt.NoFocus)
            v.addWidget(b)

        v.addWidget(QLabel("方向（按住移动）"))
        pad = QGridLayout()
        pad.addWidget(self._move_button("↖ 左转", yaw=-MOVE_YAW), 0, 0)
        pad.addWidget(self._move_button("↑ 前", vx=MOVE_XY), 0, 1)
        pad.addWidget(self._move_button("↗ 右转", yaw=MOVE_YAW), 0, 2)
        pad.addWidget(self._move_button("← 左", vy=-MOVE_XY), 1, 0)
        pad.addWidget(self._move_button("O 悬停", clear=True), 1, 1)
        pad.addWidget(self._move_button("→ 右", vy=MOVE_XY), 1, 2)
        pad.addWidget(self._move_button("↓ 后", vx=-MOVE_XY), 2, 0)
        pad.addWidget(self._move_button("↑ 升", vz=MOVE_Z), 2, 1)
        pad.addWidget(self._move_button("↓ 降", vz=-MOVE_Z), 2, 2)
        v.addLayout(pad)

        warn = QLabel(
            "注意：停止/急停会立刻切断电机，空中会直接掉下。\n"
            "优先使用降落。飞行前确认电池 ≥ 3.9 V、桨叶完好、净空 ≥ 2 m。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#e67e22; font-size:13px;")
        v.addWidget(warn)
        v.addStretch(1)
        return box

    def _move_button(self, text, clear=False, **vec):
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.NoFocus)

        def _press():
            if clear:
                self._set_input(vx=0.0, vy=0.0, vz=0.0, yaw=0.0)
            else:
                self._set_input(**vec)

        def _release():
            if not clear:
                self._set_input(**{k: 0.0 for k in vec})

        btn.pressed.connect(_press)
        btn.released.connect(_release)
        return btn

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #

    def _set_input(self, **kw):
        for k, v in kw.items():
            self._active[k] = v
        self._apply_input()

    def _apply_input(self):
        a = self._active
        if any(a.values()):
            self._ctrl.request(
                "move", vx=a["vx"], vy=a["vy"], vz=a["vz"], yawrate=a["yaw"]
            )
            if not self._move_timer.isActive():
                self._move_timer.start()
        else:
            self._ctrl.request("hover")
            self._move_timer.stop()

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_X:
            self._ctrl.request("estop")
            self._log("[GUI] 急停！")
            event.accept()
            return
        if k == Qt.Key_T:
            self._ctrl.request("takeoff", height=self._spin_height.value())
            event.accept()
            return
        if k == Qt.Key_L:
            self._ctrl.request("land")
            event.accept()
            return
        if k == Qt.Key_H:
            self._ctrl.request("hover")
            event.accept()
            return
        if k == Qt.Key_Escape:
            self._ctrl.request("stop")
            event.accept()
            return

        if k == Qt.Key_W or k == Qt.Key_Up:
            self._set_input(vx=MOVE_XY)
        elif k == Qt.Key_S or k == Qt.Key_Down:
            self._set_input(vx=-MOVE_XY)
        elif k == Qt.Key_D or k == Qt.Key_Right:
            self._set_input(vy=MOVE_XY)
        elif k == Qt.Key_A or k == Qt.Key_Left:
            self._set_input(vy=-MOVE_XY)
        elif k == Qt.Key_Space:
            self._set_input(vz=MOVE_Z)
        elif k == Qt.Key_Shift:
            self._set_input(vz=-MOVE_Z)
        elif k == Qt.Key_E:
            self._set_input(yaw=MOVE_YAW)
        elif k == Qt.Key_Q:
            self._set_input(yaw=-MOVE_YAW)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        k = event.key()
        if k in (Qt.Key_W, Qt.Key_Up):
            self._set_input(vx=0.0)
        elif k in (Qt.Key_S, Qt.Key_Down):
            self._set_input(vx=0.0)
        elif k in (Qt.Key_D, Qt.Key_Right):
            self._set_input(vy=0.0)
        elif k in (Qt.Key_A, Qt.Key_Left):
            self._set_input(vy=0.0)
        elif k == Qt.Key_Space:
            self._set_input(vz=0.0)
        elif k == Qt.Key_Shift:
            self._set_input(vz=0.0)
        elif k == Qt.Key_E:
            self._set_input(yaw=0.0)
        elif k == Qt.Key_Q:
            self._set_input(yaw=0.0)
        else:
            super().keyReleaseEvent(event)
            return
        event.accept()

    # ------------------------------------------------------------------ #
    # Periodic refresh
    # ------------------------------------------------------------------ #

    def _tick(self):
        s = self._ctrl.snapshot()

        if s["connected"]:
            status = "飞行中" if s["flying"] else "已连接"
            self._lbl_status.setText(status)
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: %s;"
                % ("#27ae60" if s["flying"] else "#2ecc71")
            )
        else:
            self._lbl_status.setText("未连接（自动重连中...）")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #e74c3c;"
            )

        self._lbl_battery.setText(f"{s['battery_v']:.2f} V")
        self._bar_battery.setValue(int(s["battery_v"] * 100))
        self._bar_battery.setFormat(f"电池 {s['battery_v']:.2f} V")
        color = "#27ae60"
        if s["battery_v"] and s["battery_v"] < 3.7:
            color = "#e74c3c"
        elif s["battery_v"] and s["battery_v"] < 3.8:
            color = "#e67e22"
        self._lbl_battery.setStyleSheet(f"color: {color}; font-weight: bold;")

        self._lbl_link.setText(f"{s['link_quality']:.0f} %")
        self._bar_link.setValue(int(s["link_quality"]))
        self._bar_link.setFormat(f"链路 {s['link_quality']:.0f} %")
        self._bar_alt.setValue(int(s["z"] * 100))
        self._bar_alt.setFormat(f"高度 {s['z']:.2f} m")
        self._traj.add_point(s["x"], s["y"], s["yaw"])
        self._lbl_pos.setText(f"{s['x']:7.2f} / {s['y']:7.2f} / {s['z']:7.2f}")
        self._lbl_atti.setText(
            f"{s['roll']:7.1f} / {s['pitch']:7.1f} / {s['yaw']:7.1f}"
        )
        self._attitude.set_attitude(s["roll"], s["pitch"], s["yaw"])

        if s["flying"]:
            self._flash = not self._flash
            bg = "#e74c3c" if self._flash else "#a93226"
            self._btn_estop.setStyleSheet(
                f"background:{bg}; color:white; font-weight:bold;"
                "font-size:24px; padding:22px; border-radius:8px;"
            )
        else:
            self._btn_estop.setStyleSheet(
                "background:#c0392b; color:white; font-weight:bold;"
                "font-size:24px; padding:22px; border-radius:8px;"
            )

        if s["locked"]:
            self._lbl_locked.setText("⚠ LOCKED：请断电重启无人机后再起飞")
        else:
            self._lbl_locked.setText("")

        for line in self._ctrl.drain_log():
            self._log(line)

        self._update_video()

    def _update_video(self):
        frame = self._video.latest()
        if not frame:
            return
        pm = QPixmap()
        if pm.loadFromData(frame, "JPG"):
            if self._chk_flip.isChecked():
                pm = pm.transformed(QTransform().rotate(180))
            self._lbl_video.setPixmap(
                pm.scaled(
                    self._lbl_video.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )

    def _on_reconnect_video(self):
        url = self._edit_url.text().strip()
        if not url:
            return
        self._video.set_url(url)
        self._video.restart()
        self._log(f"[GUI] 视频地址已切换: {url}")

    def _log(self, msg):
        self._log_view.appendPlainText(
            f"[{__import__('time').strftime('%H:%M:%S')}] {msg}"
        )

    def shutdown(self):
        self._timer.stop()
        self._move_timer.stop()
        if self._chat_panel is not None:
            self._chat_panel.shutdown()
        self._ctrl.request("hover")

    def closeEvent(self, event):
        self.shutdown()
        event.accept()
