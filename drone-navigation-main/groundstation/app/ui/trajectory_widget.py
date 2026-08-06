"""Top-down XY trajectory view: intuitive position feedback.

Screen mapping: +X (forward) is up, +Y (left) is right.  The green
triangle is the drone, oriented by its yaw.  Grid lines are 0.5 m apart.
"""

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class TrajectoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = deque(maxlen=600)
        self._yaw = 0.0
        self._home = (0.0, 0.0)
        self.setMinimumSize(300, 180)

    def add_point(self, x, y, yaw):
        self._points.append((x, y))
        self._yaw = yaw
        self.update()

    def reset(self):
        self._points.clear()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) / 2.0 - 12

        p.fillRect(self.rect(), QColor(13, 17, 23))

        # data span (auto-fit, at least 0.6 m)
        max_abs = 0.6
        for x, y in self._points:
            max_abs = max(max_abs, abs(x), abs(y))
        scale = r / max_abs

        # grid (0.5 m, fall back to 1 m if too dense)
        grid = 0.5
        step = grid * scale
        if step < 16:
            grid = 1.0
            step = grid * scale
        p.setPen(QPen(QColor(40, 48, 60), 1))
        n = int(max_abs / grid) + 2
        for i in range(-n, n + 1):
            off = i * step
            if abs(off) > r:
                continue
            p.drawLine(QPointF(cx - r, cy + off), QPointF(cx + r, cy + off))
            p.drawLine(QPointF(cx + off, cy - r), QPointF(cx + off, cy + r))

        # axes
        p.setPen(QPen(QColor(90, 100, 120), 1))
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))

        def to_screen(x, y):
            # +X forward -> up, +Y left -> right
            return QPointF(cx + y * scale, cy - x * scale)

        # trajectory trail
        if len(self._points) > 1:
            pen = QPen(QColor(46, 204, 113), 2)
            pen.setCosmetic(True)
            p.setPen(pen)
            pts = [to_screen(x, y) for x, y in self._points]
            p.drawPolyline(pts)

        # home cross (green)
        p.setPen(QPen(QColor(46, 204, 113), 2))
        hp = to_screen(*self._home)
        p.drawLine(QPointF(hp.x() - 8, hp.y()), QPointF(hp.x() + 8, hp.y()))
        p.drawLine(QPointF(hp.x(), hp.y() - 8), QPointF(hp.x(), hp.y() + 8))

        # current position: aircraft triangle oriented by yaw
        if self._points:
            x, y = self._points[-1]
            sp = to_screen(x, y)
            p.save()
            p.translate(sp.x(), sp.y())
            p.rotate(-self._yaw)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.setBrush(QColor(46, 204, 113))
            p.drawPolygon(
                QPolygonF(
                    [
                        QPointF(0, -14),
                        QPointF(-9, 8),
                        QPointF(9, 8),
                    ]
                )
            )
            p.restore()

        # labels
        p.setPen(QColor(150, 160, 175))
        p.drawText(QRectF(6, 2, w - 12, 18), Qt.AlignLeft, "俯视位置 (米)")
        if self._points:
            x, y = self._points[-1]
            p.drawText(
                QRectF(6, h - 22, w - 12, 18),
                Qt.AlignRight,
                f"x={x:6.2f}  y={y:6.2f}  yaw={self._yaw:6.1f}°",
            )
