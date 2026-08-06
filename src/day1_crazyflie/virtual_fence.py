"""Virtual fence for the Day-1 flight mission (进阶技能, 80 pts).

A "virtual fence" is a box around the take-off point that the drone must never
leave.  The Crazyflie has no GPS, so we build the fence on top of whatever
position estimate is available:

* If a Flow deck (optical flow + height sensor) is mounted, the on-board
  Kalman estimator produces usable world-frame x/y/z — the fence then enforces
  *measured* position.
* Without a Flow deck, x/y is basically unusable.  We then integrate the
  measured world-frame velocity (stateEstimate.vx/vy/vz) into a pseudo-position
  so the fence is still enforced on a best-effort basis.  Height always comes
  from the barometer and is reliable either way.

Two layers of protection are provided:

1. :meth:`clamp_displacement` — called *before* every move command.  It
   shortens the requested displacement so the planned end point stays inside
   the box.  The drone never gets told to fly out.
2. :class:`FenceMonitor` — a background thread that watches the live position
   during flight and, if the drone still drifts out, stops it and signals an
   emergency landing.  This is the safety net for controller overshoot.
"""
import threading
import time


class VirtualFence:
    """Axis-aligned box: [x_min, x_max] x [y_min, y_max] x [z_min, z_max]."""

    def __init__(self, x_min=-1.0, x_max=1.0,
                 y_min=-1.0, y_max=1.0,
                 z_min=0.05, z_max=1.5,
                 margin=0.15):
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max
        self.z_min, self.z_max = z_min, z_max
        self.margin = margin  # keep-away distance from every wall (m)

    def in_bounds(self, x, y, z):
        """True if the point is inside the box (with margin)."""
        return (self.x_min + self.margin <= x <= self.x_max - self.margin and
                self.y_min + self.margin <= y <= self.y_max - self.margin and
                self.z_min <= z <= self.z_max - self.margin)

    def clamp_point(self, x, y, z):
        """Snap a point back into the box (used to bound the take-off point)."""
        x = min(max(x, self.x_min + self.margin), self.x_max - self.margin)
        y = min(max(y, self.y_min + self.margin), self.y_max - self.margin)
        z = min(max(z, self.z_min), self.z_max - self.margin)
        return x, y, z

    def clamp_displacement(self, dx, dy, dz, x, y, z):
        """Shrink (dx, dy, dz) so the end point stays inside the box.

        ``(x, y, z)`` is the current position estimate.  Returns the adjusted
        displacement — a zero vector when there is no room left to move.
        """
        tx, ty, tz = x + dx, y + dy, z + dz
        tx, ty, tz = self.clamp_point(tx, ty, tz)
        return tx - x, ty - y, tz - z

    def describe(self):
        return (f'[{self.x_min}, {self.x_max}] x '
                f'[{self.y_min}, {self.y_max}] x '
                f'[{self.z_min}, {self.z_max}] m (margin {self.margin} m)')


class FenceMonitor:
    """Background watchdog: aborts the flight if the drone leaves the fence.

    ``pos_fn`` returns the current estimated (x, y, z) position or ``None``.
    On the first violation it sets ``abort_event`` and — if ``stop_cmd`` is
    given — stops the motors (thread-safe: it only queues a setpoint).
    """

    def __init__(self, fence, pos_fn, abort_event, on_violation,
                 stop_cmd=None, period_s=0.1):
        self._fence = fence
        self._pos_fn = pos_fn
        self._abort = abort_event
        self._on_violation = on_violation
        self._stop_cmd = stop_cmd
        self._period = period_s
        self._thread = None
        self._violation_seen = False

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        while not self._abort.is_set():
            pos = self._pos_fn()
            if pos is not None and not self._fence.in_bounds(*pos):
                if not self._violation_seen:
                    self._violation_seen = True
                    self._abort.set()
                    if self._stop_cmd is not None:
                        self._stop_cmd()
                    self._on_violation(pos)
                break
            time.sleep(self._period)


class PositionIntegrator:
    """Integrates measured world velocity into a pseudo x/y position.

    Used only when the drone has no Flow deck, i.e. when stateEstimate.x/y is
    not trustworthy.  This lets the fence degrade gracefully instead of failing
    closed.  Drift accumulates — treat it as advisory, not ground truth.
    """

    def __init__(self, telemetry):
        self._telemetry = telemetry
        self.x = 0.0
        self.y = 0.0
        self._last = None

    def update(self):
        vx = self._telemetry.get('stateEstimate.vx')
        vy = self._telemetry.get('stateEstimate.vy')
        now = time.time()
        if vx is not None and vy is not None:
            if self._last is not None:
                dt = now - self._last
                self.x += vx * dt
                self.y += vy * dt
            self._last = now
        else:
            self._last = now
        return self.x, self.y
