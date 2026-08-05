"""Emergency-key listener + emergency-landing helpers for the
simple_crazyflie scripts.

Pressing the key (default **X**, case-insensitive) at any time triggers:
- an immediate motor stop during the individual spin checks, or
- a rapid, controlled landing while the drone is hovering/flying.

Pure standard library (termios/tty/select) — no extra pip packages.
Requires a real terminal; in a non-TTY context the listener simply
does nothing and the scripts still work.

Usage:
    from emergency_key import EmergencyKey, EmergencyLanding, emergency_land

    ek = EmergencyKey()      # key='x'
    ek.start()
    ...
    if ek.triggered():       # or catch EmergencyLanding raised in loops
        ...
    ...
    ek.stop()                # always call before exiting (restores TTY)
"""
import select
import sys
import termios
import threading
import time
import tty


class EmergencyLanding(Exception):
    """Raised by flight/hover loops when the emergency key is pressed."""


class EmergencyKey:
    """Watch the terminal for the emergency key on a background thread."""

    def __init__(self, key='x'):
        self._key = key.lower()
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        fd = sys.stdin.fileno()
        old = None
        try:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while not self._stop.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    ch = sys.stdin.read(1)
                    if ch and ch.lower() == self._key:
                        self._event.set()
        except Exception:
            # Not a TTY (e.g. piped) — the listener is simply inert.
            pass
        finally:
            if old is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except Exception:
                    pass

    def triggered(self):
        """True once the key has been pressed (stays set until stop())."""
        return self._event.is_set()

    def stop(self):
        """Stop the listener and restore the terminal."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None


def emergency_land(cf, z_current, rate=20.0, duration=1.5, settle=1.0):
    """Rapid but controlled descent from *z_current* to the ground.

    Sends hover setpoints at ~rate Hz: a quick ramp of z to 0, then a
    short z=0 hold so the drone physically settles before the caller
    cuts the motors (avoids latching the LOCKED supervisor state).
    """
    step = 1.0 / rate
    steps = int(duration * rate)
    for i in range(1, steps + 1):
        z = z_current * (1 - i / steps)
        cf.commander.send_hover_setpoint(0, 0, 0, z)
        time.sleep(step)
    deadline = time.monotonic() + settle
    while time.monotonic() < deadline:
        cf.commander.send_hover_setpoint(0, 0, 0, 0)
        time.sleep(step)
