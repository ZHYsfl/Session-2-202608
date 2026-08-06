"""SimMotionCommander — a dry-run stand-in for cflib's MotionCommander.

It mirrors the same public API and the same semantics:

* distance primitives (``forward/back/left/right/up/down``) run a body-frame
  velocity for ``distance/velocity`` seconds;
* velocity primitives (``start_forward/start_back/...``) keep a velocity until
  ``stop()`` is called;
* a background thread integrates body-frame velocity into a world-frame
  position using the current yaw — exactly what the real firmware does with
  hover setpoints.

This lets us verify the virtual-fence logic, the mission sequence and the CSV
output *without any hardware*, which is also handy for the day-1 write-up
(simulated trajectory vs. real flight can be compared).

This is NOT flight software — it is a deterministic model for testing.
"""
import math
import threading
import time


class SimMotionCommander:
    """Drop-in replacement for cflib.positioning.motion_commander.MotionCommander."""

    def __init__(self, default_height=0.3):
        self.default_height = default_height
        self._flying = False
        self._vx = self._vy = self._vz = 0.0
        self._yaw_rate = 0.0
        self._x = self._y = self._z = 0.0
        self._yaw = 0.0
        self.commands = []          # human-readable command log
        self._stop = threading.Event()
        self._thread = None

    # -- distance primitives (same as MotionCommander) -----------------------
    def forward(self, d, velocity=0.2): self.move_distance(d, 0, 0, velocity)
    def back(self, d, velocity=0.2): self.move_distance(-d, 0, 0, velocity)
    def left(self, d, velocity=0.2): self.move_distance(0, d, 0, velocity)
    def right(self, d, velocity=0.2): self.move_distance(0, -d, 0, velocity)
    def up(self, d, velocity=0.2): self.move_distance(0, 0, d, velocity)
    def down(self, d, velocity=0.2): self.move_distance(0, 0, -d, velocity)

    def move_distance(self, dx, dy, dz, velocity=0.2):
        dist = math.hypot(dx, dy, dz)
        if dist < 1e-9:
            self.stop()
            return
        duration = dist / velocity
        self.commands.append(
            f'move ({dx:+.2f},{dy:+.2f},{dz:+.2f}) m @ {velocity} m/s '
            f'for {duration:.2f} s')
        self.start_linear_motion(velocity * dx / dist, velocity * dy / dist,
                                 velocity * dz / dist)
        time.sleep(duration)
        self.stop()

    def turn_left(self, angle_degrees, rate=72.0):
        self.commands.append(f'turn_left {angle_degrees:.0f} deg @ {rate} deg/s')
        self.start_turn_left(rate)
        time.sleep(angle_degrees / rate)
        self.stop()

    def turn_right(self, angle_degrees, rate=72.0):
        self.commands.append(f'turn_right {angle_degrees:.0f} deg @ {rate} deg/s')
        self.start_turn_right(rate)
        time.sleep(angle_degrees / rate)
        self.stop()

    # -- velocity primitives (same as MotionCommander) -----------------------
    def start_left(self, velocity=0.2): self.start_linear_motion(0, velocity, 0)
    def start_right(self, velocity=0.2): self.start_linear_motion(0, -velocity, 0)
    def start_forward(self, velocity=0.2): self.start_linear_motion(velocity, 0, 0)
    def start_back(self, velocity=0.2): self.start_linear_motion(-velocity, 0, 0)
    def start_up(self, velocity=0.2): self.start_linear_motion(0, 0, velocity)
    def start_down(self, velocity=0.2): self.start_linear_motion(0, 0, -velocity)
    def start_turn_left(self, rate=72.0): self.start_linear_motion(0, 0, 0, rate)
    def start_turn_right(self, rate=72.0): self.start_linear_motion(0, 0, 0, -rate)

    def start_linear_motion(self, vx, vy, vz, rate_yaw=0.0):
        if not self._flying:
            raise Exception('Can not move on the ground. Take off first!')
        self.commands.append(
            f'vel (vx={vx:+.2f}, vy={vy:+.2f}, vz={vz:+.2f}) yawrate={rate_yaw:+.1f}')
        self._set_velocity(vx, vy, vz, rate_yaw)

    def stop(self):
        self._set_velocity(0, 0, 0, 0)

    # -- lifecycle ------------------------------------------------------------
    def take_off(self, height=None, velocity=0.2):
        if self._flying:
            raise Exception('Already flying')
        self._flying = True
        target = self.default_height if height is None else height
        self.commands.append(f'take_off to {target} m')
        self._z = target
        self._start_thread()

    def land(self, velocity=0.2):
        if self._flying:
            self.commands.append(f'land (from z={self._z:.2f} m)')
            self._flying = False
            self._stop_thread()
            self._set_velocity(0, 0, 0, 0)

    def __enter__(self):
        self.take_off()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.land()

    # -- internal ---------------------------------------------------------------
    def _set_velocity(self, vx, vy, vz, yaw_rate):
        self._vx, self._vy, self._vz = vx, vy, vz
        self._yaw_rate = yaw_rate

    def _start_thread(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._integrate, daemon=True)
        self._thread.start()

    def _stop_thread(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _integrate(self):
        while not self._stop.is_set():
            t0 = time.time()
            time.sleep(0.05)
            dt = time.time() - t0
            rad = math.radians(self._yaw)
            c, s = math.cos(rad), math.sin(rad)
            # body -> world (forward vx, left vy; yaw CCW from above)
            self._x += (self._vx * c - self._vy * s) * dt
            self._y += (self._vx * s + self._vy * c) * dt
            self._z += self._vz * dt
            self._yaw += self._yaw_rate * dt

    @property
    def position(self):
        return self._x, self._y, self._z

    @property
    def yaw_deg(self):
        return self._yaw

    def print_commands(self):
        print('--- 仿真指令日志 ---')
        for cmd in self.commands:
            print('  ' + cmd)
        print(f'最终位置: ({self._x:.2f}, {self._y:.2f}, {self._z:.2f}) m, '
              f'yaw={self._yaw:.1f} deg')
