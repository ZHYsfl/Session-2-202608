"""Entry point: launch the Crazyflie QT ground station GUI."""

import sys


def main():
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont, QFontDatabase
    except ImportError:
        print("PySide6 未安装，请执行: pip install PySide6")
        sys.exit(1)

    from app.command_server import CommandServer
    from app.config import load_config
    from app.controller import CrazyflieController
    from app.openclaw_client import OpenClawChat
    from app.ui.main_window import MainWindow
    from app.video import MjpegFetcher

    cfg = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("Crazyflie Ground Station")

    # Prefer a CJK-capable font so Chinese UI text renders correctly in WSL.
    # If none is found (e.g. fonts-noto-cjk not installed), print a hint.
    available = set(QFontDatabase.families())
    chosen = None
    for family in (
        "Noto Sans CJK SC",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "SimHei",
    ):
        if family in available:
            chosen = family
            break
    if chosen:
        ui_font = QFont(chosen)
        ui_font.setPointSize(12)
        app.setFont(ui_font)
        print(f"[GS] 界面字体: {chosen}")
    else:
        print("[GS] 提示: 未找到中文字体，中文可能显示为方块。")
        print("[GS] 请在 WSL 里执行: sudo apt install -y fonts-noto-cjk")

    controller = CrazyflieController(cfg["radio_uri"])
    controller.start()

    video = MjpegFetcher(cfg.get("camera_url", ""))
    video.start()

    oc_cfg = cfg.get("openclaw", {}) or {}
    chat = None
    if oc_cfg.get("base_url"):
        chat = OpenClawChat(
            base_url=oc_cfg.get("base_url", "http://127.0.0.1:18789"),
            token=oc_cfg.get("token", ""),
            model=oc_cfg.get("model", "openclaw/default"),
            user=oc_cfg.get("user", "groundstation-gui"),
        )

    win = MainWindow(controller, video, cfg, chat=chat)
    win.showMaximized()

    # Also expose the local HTTP API while the GUI is open, so OpenClaw
    # can drive the drone at the same time.
    if cfg.get("command_server_port"):
        try:
            server = CommandServer(
                controller,
                host=cfg.get("command_server_host", "127.0.0.1"),
                port=int(cfg["command_server_port"]),
                token=cfg.get("command_server_token") or None,
            )
            server.start()
            print(f"[GS] HTTP command API: http://127.0.0.1:{server.port}")
        except Exception as exc:
            print(f"[GS] HTTP command API disabled: {exc}")
            server = None
    else:
        server = None

    rc = app.exec()

    if server is not None:
        server.stop()
    video.stop()
    controller.stop()
    sys.exit(rc)


if __name__ == "__main__":
    main()
