r"""Slowly spin each motor individually — propeller direction / blade check.

Same individual-motor check as the first half of 03_propellers.py,
but WITHOUT the short hover.  Useful when you only want to verify
that each propeller is spinning slowly in the right direction
(e.g. to identify a flipped / wrong-CW-CCW propeller on the bench).

The Crazyflie 2.1 motor layout (X-configuration, top-down view):

             Front
        M4 (CW)    M1 (CCW)
             \    /
              \  /
              /  \
             /    \
        M3 (CCW)   M2 (CW)
             Back

Each motor must spin in the direction shown AND carry the matching
propeller type (CW or CCW).  A wrong prop or wrong motor order makes
the drone flip on takeoff.

Run:  python 05_spin_test.py            # default: 15% power, 3 s each
      python 05_spin_test.py 12000       # custom power (0..65535)
      python 05_spin_test.py 12000 4     # custom power + seconds per motor

This test works even when the drone is in the LOCKED supervisor state
and does NOT lift off (motors are driven directly via motorPowerSet,
bypassing the flight controller).  The drone is NOT armed.
"""
import logging
import sys
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

from emergency_key import EmergencyKey, EmergencyLanding

URI = 'radio://0/12/2M/8A3F5C2D9E'
POWER = 10000          # ~15 % — slow, clearly visible spin
SPIN_TIME = 3.0        # seconds per motor
PAUSE = 1.5            # between motors

DIAGRAM = """\
               Front
          M4 (CW)    M1 (CCW)
               \\    /
                \\  /
                /  \\
               /    \\
          M3 (CCW)   M2 (CW)
               Back"""

logging.basicConfig(level=logging.ERROR)

warnings.filterwarnings(
    'ignore',
    message=r'Using legacy TYPE_.*_LEGACY',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'platform\.send_arming_request is deprecated',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'The supervisor subsystem requires CRTP protocol version 12 or later',
    category=UserWarning,
)


def _spin_each_motor(cf, power, spin_time, ek=None):
    """Spin each motor one at a time at low power; user verifies direction."""
    print()
    print('Individual motor check — watch each propeller as it spins')
    print('-' * 50)
    print()
    print('  Top view (front of the drone pointing away from you):')
    print()
    print(DIAGRAM)
    print()
    print(f'  Power: {power} (~{power / 65535 * 100:.0f}%)  '
          f'{spin_time:.0f} s per motor — slow on purpose.')
    print()
    motors = [
        ('M1', 'm1', 'front-right', 'counter-clockwise ↺'),
        ('M2', 'm2', 'rear-right ', 'clockwise ↻'),
        ('M3', 'm3', 'rear-left  ', 'counter-clockwise ↺'),
        ('M4', 'm4', 'front-left ', 'clockwise ↻'),
    ]
    for tag, param, pos, direction in motors:
        print(f'  {tag} ({pos}) — expect {direction}')
        print(f'      spinning for {spin_time:.0f} s ... '
              f'(press X to stop)', flush=True)
        try:
            cf.param.set_value(f'motorPowerSet.{param}', power)
            deadline = time.monotonic() + spin_time
            while time.monotonic() < deadline:
                if ek is not None and ek.triggered():
                    raise EmergencyLanding()
                time.sleep(0.05)
        except KeyError as e:
            # TOC mismatch (e.g. stale cache) — never crash mid-test.
            print(f'  ⚠️  cannot set {tag}: {e}')
        finally:
            # Always zero the current motor, even on an emergency stop;
            # never let the zeroing itself raise (a stuck motor is worse).
            try:
                cf.param.set_value(f'motorPowerSet.{param}', 0)
            except Exception as e2:
                print(f'  ⚠️  failed to zero {tag}: {e2}')
        time.sleep(PAUSE)
    print()
    print('  Checklist:')
    print('    [ ] M1 — front-right — counter-clockwise ↺')
    print('    [ ] M2 — rear-right  — clockwise ↻')
    print('    [ ] M3 — rear-left   — counter-clockwise ↺')
    print('    [ ] M4 — front-left  — clockwise ↻')
    print()
    print('  A motor that did not spin: check wiring/connectors.')
    print('  A prop that visibly does NOT lift air: it may be the')
    print('  wrong CW/CCW type or mounted upside down.')
    print()


if __name__ == '__main__':
    power = POWER
    spin_time = SPIN_TIME
    if len(sys.argv) > 1:
        power = int(sys.argv[1])
    if len(sys.argv) > 2:
        spin_time = float(sys.argv[2])
    if not 0 <= power <= 65535:
        sys.exit('power must be 0..65535')

    cflib.crtp.init_drivers()
    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
        time.sleep(2)

        ek = EmergencyKey()
        ek.start()
        print('  ⚠️  EMERGENCY: press X at any time to stop the current motor.')

        toc = scf.cf.param.toc.toc
        if 'motorPowerSet' not in toc or 'm1' not in toc['motorPowerSet']:
            sys.exit('motorPowerSet params not found on this firmware — '
                     'cannot do the individual spin test.')

        # Individual motor control is gated behind the enable flag.
        scf.cf.param.set_value('motorPowerSet.enable', 1)
        time.sleep(0.2)
        try:
            _spin_each_motor(scf.cf, power, spin_time, ek)
        except EmergencyLanding:
            print('\n[EMERGENCY] X pressed — motors stopped.')
        except KeyboardInterrupt:
            print('\n[Ctrl+C] — aborting the test.')
        finally:
            # Always hand motor control back to the flight controller
            # and cut the motors, so leftover state can never block a
            # later flight.
            for m in ('m1', 'm2', 'm3', 'm4'):
                try:
                    scf.cf.param.set_value(f'motorPowerSet.{m}', 0)
                except Exception:
                    pass
            try:
                scf.cf.param.set_value('motorPowerSet.enable', 0)
            except Exception:
                pass
            scf.cf.commander.send_stop_setpoint()
            scf.cf.commander.send_notify_setpoint_stop()
            time.sleep(0.3)
            ek.stop()

    print('\nDone. No hover was performed.')
    print('Remember: correct propeller TYPES (CW/CCW) are just as '
          'important as direction.')
