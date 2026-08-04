r"""First flight — take off, hover, land.

Run:  python 04_flying.py

How this drone arms — READ THIS FIRST
-------------------------------------
This drone runs a modified firmware build (CRTP protocol v6,
firmware.modified = 1).  Its arming switch is the PARAMETER
``system.arm``:

    system.arm = 1  -> armed: the flight controller drives the motors
    system.arm = 0  -> disarmed: controller output is blocked and the
                       motors stay off no matter what setpoints are sent

cflib's platform.send_arming_request() sends a CRTP platform packet
that THIS firmware silently ignores — the only arming switch it honours
is the system.arm parameter.

Also required for normal flight: motorPowerSet.enable must be 0.  With
enable = 1 the motor outputs are overridden by the motorPowerSet.m1..m4
params and the flight controller is ignored.

The LOCKED trap — why landing gently matters
--------------------------------------------
If the motors are cut while the supervisor still believes the drone is
airborne (an abrupt stop right after the altitude setpoint hits zero,
before the drone physically touches down), the firmware latches a
LOCKED state (bit 6 of supervisor.info, sys.canfly = 0).  The same
lock also engages after a crash or tumble in flight — by design; a
crashed drone stays locked until it is power-cycled.  Once locked,
arming appears to succeed but the motors never spin, and nothing
clears it over the radio (the crash-recovery command is ignored).
Prevention: descend on a long ramp, then keep feeding a z=0
altitude-hold setpoint for a couple of seconds before cutting the
motors.  Note: sys.isFlying never clears on this firmware, so the
settle below is time-based, not flag-based.

Flight mechanism: hover setpoints (TYPE_HOVER_LEGACY on this CRTP v6
firmware) pumped at 20 Hz.  Altitude hold uses the flow deck's distance
sensor, which is working (range.zrange reads the real height above
ground).  Ctrl+C cuts the motors immediately and disarms.
"""
import logging
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

# URI of the Crazyflie to connect to (radio link via the Crazyradio PA):
#   radio://<dongle>/<channel>/<datarate>/<address>
URI = 'radio://0/80/2M/E7E7E7E7E7'

TAKEOFF_HEIGHT = 0.3   # metres — conservative first-flight height
TAKEOFF_TIME = 3.0     # seconds to ramp from 0 to TAKEOFF_HEIGHT
HOVER_TIME = 5.0       # seconds to hover at altitude
LAND_TIME = 3.0        # seconds to ramp back down to 0
RATE = 20.0            # Hz — setpoint rate
STEP = 1.0 / RATE
SETTLE_TIME = 2.0      # seconds of z=0 altitude hold after the descent

LOCKED_BIT = 0x40      # supervisor.info bit 6 — "must be restarted"

logging.basicConfig(level=logging.ERROR)

# This drone runs a custom firmware build (CRTP protocol v6). cflib emits
# a compatibility warning for the legacy hover packet type — the legacy
# codepath is exactly what this firmware needs. Suppress it.
warnings.filterwarnings(
    'ignore',
    message=r'Using legacy TYPE_.*_LEGACY',
    category=DeprecationWarning,
)

# Live supervisor flags, refreshed by the log callback below.
_state = {'flying': 1, 'sup': 0}


def _state_cb(ts, data, conf):
    _state['flying'] = data.get('sys.isFlying', 1)
    _state['sup'] = data.get('supervisor.info', 0)


def _start_state_log(cf):
    lg = LogConfig(name='FlyState', period_in_ms=100)
    lg.add_variable('sys.isFlying', 'uint8_t')
    lg.add_variable('supervisor.info', 'uint16_t')
    cf.log.add_config(lg)
    lg.data_received_cb.add_callback(_state_cb)
    lg.start()
    return lg


def _locked():
    return bool(_state['sup'] & LOCKED_BIT)


def _send(cf, vx, vy, yawrate, zdistance):
    cf.commander.send_hover_setpoint(vx, vy, yawrate, zdistance)


def _hold(cf, zdistance, duration):
    """Pump a constant-altitude hover setpoint for *duration* seconds."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        _send(cf, 0, 0, 0, zdistance)
        time.sleep(STEP)


def _ramp(cf, z_start, z_end, duration):
    """Linearly ramp the altitude setpoint between two values."""
    steps = int(duration * RATE)
    for i in range(1, steps + 1):
        z = z_start + (z_end - z_start) * i / steps
        _send(cf, 0, 0, 0, z)
        time.sleep(STEP)


def _settle(cf, duration=SETTLE_TIME):
    """Keep feeding z=0 altitude hold after the descent ramp.

    Cutting the motors abruptly the instant the setpoint reaches zero
    (the drone still airborne) latches the LOCKED state, which needs a
    power cycle to clear.  Pumping z=0 for a couple of seconds lets the
    drone physically settle before the cut.  (The supervisor's
    sys.isFlying flag never clears on this firmware, so the settle is
    time-based rather than flag-based.)
    """
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        _send(cf, 0, 0, 0, 0)
        time.sleep(STEP)


def _arm(cf):
    """Arm via the system.arm parameter.  Returns True on success."""
    cf.param.set_value('system.arm', 1)
    time.sleep(0.3)
    return str(cf.param.get_value('system.arm')) == '1'


def _disarm(cf):
    try:
        cf.param.set_value('system.arm', 0)
    except Exception:
        pass


if __name__ == '__main__':
    cflib.crtp.init_drivers()

    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
        cf = scf.cf
        time.sleep(1)

        lg = _start_state_log(cf)
        time.sleep(0.5)                  # let a few samples arrive

        if _locked():
            print('The drone is in the LOCKED supervisor state — a previous')
            print('flight ended with the motors cut while it was airborne.')
            print('Power-cycle the drone, then run this script again.')
            raise SystemExit(1)

        # Normal flight configuration: the flight controller drives the
        # motors.  A previous script (e.g. the propeller check) may have
        # left enable = 1, which would override the motors with the
        # motorPowerSet.m1..m4 params — clear it defensively.
        try:
            cf.param.set_value('motorPowerSet.enable', 0)
        except Exception:
            pass

        print('Arming (system.arm = 1) ...')
        if not _arm(cf):
            print('FAILED — the drone did not accept the arming request.')
            print('Power-cycle the drone, check the battery, try again.')
            raise SystemExit(1)
        print('Armed.')

        try:
            print(f'Taking off — ramping to {TAKEOFF_HEIGHT} m over '
                  f'{TAKEOFF_TIME:.0f} s ...')
            _ramp(cf, 0.0, TAKEOFF_HEIGHT, TAKEOFF_TIME)

            print(f'Hovering at {TAKEOFF_HEIGHT} m for {HOVER_TIME:.0f} s ...')
            _hold(cf, TAKEOFF_HEIGHT, HOVER_TIME)

            print(f'Landing over {LAND_TIME:.0f} s ...')
            _ramp(cf, TAKEOFF_HEIGHT, 0.0, LAND_TIME)

            print('Touching down — holding z=0 while the drone settles ...')
            _settle(cf)
            print('Landed.')
        except KeyboardInterrupt:
            print('\n[Ctrl+C] — cutting motors immediately.')
        finally:
            # Stop setpoints, tell the firmware no more are coming
            # (hand back to the watchdog so it cuts the motors), disarm.
            cf.commander.send_stop_setpoint()
            time.sleep(0.1)
            cf.commander.send_notify_setpoint_stop()
            _disarm(cf)
            time.sleep(0.3)
            if _locked():
                print('Motors off — NOTE: the drone latched into the LOCKED')
                print('state.  Power-cycle it before the next flight.')
            else:
                print('Motors off — drone disarmed.')
