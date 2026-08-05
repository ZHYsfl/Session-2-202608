"""Attitude gauges: roll dial + pitch bubble bar + yaw compass.

Three simple, labelled readouts instead of an abstract horizon ball:
  - Roll:   arc dial with a needle, -90..+90 deg
  - Pitch:  vertical bubble level, +30..-30 deg
  - Yaw:    round compass with a fixed nose marker
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class AttitudeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw = 0.0
        self.setMinimumSize(300, 300)

    def set_attitude(self, roll, pitch, yaw):
        self._roll = roll
        self._pitch = pitch
        self._yaw = yaw
        self.update()

    def _label(self, p, rect, text):
        font = p.font()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(210, 215, 220))
        p.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        top_h = h * 0.44

        # ------------------------------------------------------------------ #
        # 1) ROLL: arc dial (left top)
        # ------------------------------------------------------------------ #
        roll_cx = w * 0.26
        roll_cy = top_h * 0.58
        roll_r = min(w * 0.24, top_h * 0.40)
        self._label(p, QRectF(roll_cx - roll_r, 2, roll_r * 2, 22), "横滚 Roll")

        # dial background arc
        arc = QRectF(roll_cx - roll_r, roll_cy - roll_r, roll_r * 2, roll_r * 2)
        p.setPen(QPen(QColor(60, 70, 84), 2))
        p.setBrush(QColor(24, 30, 40))
        p.drawPie(arc, 180 * 16, 180 * 16)

        # ticks every 30 deg
        for deg in range(-90, 91, 30):
            a = math.radians(deg)
            r1 = roll_r - 8 if deg % 90 == 0 else roll_r - 4
            x1 = roll_cx + r1 * math.sin(a)
            y1 = roll_cy - r1 * math.cos(a)
            x2 = roll_cx + roll_r * math.sin(a)
            y2 = roll_cy - roll_r * math.cos(a)
            p.setPen(QPen(QColor(200, 205, 212), 2 if deg % 90 == 0 else 1))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # degree labels
        p.setPen(QColor(160, 170, 180))
        for deg, txt in ((-90, "-90"), (0, "0"), (90, "+90")):
            a = math.radians(deg)
            lx = roll_cx + (roll_r - 22) * math.sin(a)
            ly = roll_cy - (roll_r - 22) * math.cos(a)
            p.drawText(QRectF(lx - 18, ly - 10, 36, 20), Qt.AlignCenter, txt)

        # needle
        roll = max(-90.0, min(90.0, self._roll))
        a = math.radians(roll)
        p.setPen(QPen(QColor(231, 76, 60), 3))
        p.drawLine(
            QPointF(roll_cx, roll_cy),
            QPointF(roll_cx + (roll_r - 16) * math.sin(a), roll_cy - (roll_r - 16) * math.cos(a)),
        )
        p.setBrush(QColor(231, 76, 60))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(roll_cx, roll_cy), 4, 4)
        # numeric value
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRectF(roll_cx - roll_r, roll_cy + roll_r - 30, roll_r * 2, 24),
            Qt.AlignCenter,
            f"{self._roll:+6.1f}°",
        )

        # ------------------------------------------------------------------ #
        # 2) PITCH: vertical bubble bar (right top)
        # ------------------------------------------------------------------ #
        pitch_cx = w * 0.74
        bar_top = h * 0.10
        bar_bot = top_h * 0.94
        bar_mid = (bar_top + bar_bot) / 2.0
        self._label(
            p, QRectF(pitch_cx - w * 0.24, 2, w * 0.48, 22), "俯仰 Pitch"
        )

        # bar frame
        p.setPen(QPen(QColor(60, 70, 84), 2))
        p.setBrush(QColor(24, 30, 40))
        p.drawRect(QRectF(pitch_cx - 10, bar_top, 20, bar_bot - bar_top))

        # center + ticks (+30..-30 deg)
        pitch_span = 60.0
        px_per_deg = (bar_bot - bar_top) / pitch_span
        p.setPen(QPen(QColor(200, 205, 212), 1))
        for deg in range(-30, 31, 10):
            y = bar_mid + deg * px_per_deg
            p.drawLine(
                QPointF(pitch_cx - 16, y),
                QPointF(pitch_cx + 16, y),
            )
        # degree labels
        p.setPen(QColor(160, 170, 180))
        for deg in (-30, 0, 30):
            y = bar_mid + deg * px_per_deg
            p.drawText(QRectF(pitch_cx + 18, y - 10, 34, 20), Qt.AlignLeft, f"{deg:+d}")
        # bubble
        pitch = max(-30.0, min(30.0, self._pitch))
        by = bar_mid + pitch * px_per_deg
        p.setBrush(QColor(46, 204, 113))
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawEllipse(QPointF(pitch_cx, by), 8, 8)
        # numeric value
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRectF(pitch_cx - 70, bar_bot + 4, 140, 24),
            Qt.AlignCenter,
            f"{self._pitch:+6.1f}°",
        )

        # ------------------------------------------------------------------ #
        # 3) YAW: compass (bottom)
        # ------------------------------------------------------------------ #
        comp_cx = w / 2.0
        comp_cy = top_h + (h - top_h) / 2.0
        comp_r = min(w, h) * 0.21
        self._label(p, QRectF(comp_cx - comp_r, top_h + 2, comp_r * 2, 20), "航向 Yaw")

        # rotating compass card
        p.save()
        p.translate(comp_cx, comp_cy)
        p.rotate(-self._yaw)
        p.setPen(QPen(QColor(60, 70, 84), 2))
        p.setBrush(QColor(24, 30, 40))
        p.drawEllipse(QPointF(0, 0), comp_r, comp_r)
        # ticks every 30 deg, cardinal letters
        p.setPen(QPen(QColor(200, 205, 212), 1))
        for deg in range(0, 360, 30):
            a = math.radians(deg)
            r1 = comp_r - 7 if deg % 90 == 0 else comp_r - 4
            p.drawLine(
                QPointF(r1 * math.sin(a), -r1 * math.cos(a)),
                QPointF(comp_r * math.sin(a), -comp_r * math.cos(a)),
            )
        p.setPen(QColor(255, 255, 255))
        for deg, txt in (
            (0, "N"),
            (90, "E"),
            (180, "S"),
            (270, "W"),
        ):
            a = math.radians(deg)
            tx = (comp_r - 16) * math.sin(a)
            ty = -(comp_r - 16) * math.cos(a)
            p.drawText(QRectF(tx - 12, ty - 10, 24, 20), Qt.AlignCenter, txt)
        p.restore()

        # fixed nose marker
        p.setPen(QPen(QColor(231, 76, 60), 3))
        p.setBrush(QColor(231, 76, 60))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(comp_cx, comp_cy - comp_r + 2),
                    QPointF(comp_cx - 8, comp_cy - comp_r - 10),
                    QPointF(comp_cx + 8, comp_cy - comp_r - 10),
                ]
            )
        )
        # yaw value
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRectF(comp_cx - comp_r, comp_cy + comp_r - 26, comp_r * 2, 24),
            Qt.AlignCenter,
            f"{self._yaw:7.1f}°",
        )
