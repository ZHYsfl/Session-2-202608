"""Shared helpers for the Crazyflie Day-1 scripts (branch 002).

Conventions
-----------
* Coordinate frames follow the Crazyflie convention:
  +X = forward, +Y = left, +Z = up, yaw in degrees.
* Link URI format: ``radio://0/80/2M/E7E7E7E7E7``
  (Crazyradio, channel 80, 2 Mbit, radio address E7E7E7E7E7).
* All values (position, velocity, yaw) are SI: metres, m/s, degrees.
"""
import os
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.utils import uri_helper

# Default link to the Crazyflie. Override with the CRAZYFLIE_URI env var:
#   $env:CRAZYFLIE_URI = 'radio://0/80/2M/E7E7E7E7E7'
URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')

# Store the log/param TOC cache here so every script connects faster.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')


def init_drivers():
    """Initialise the CRTP radio drivers (call once per process)."""
    cflib.crtp.init_drivers()


def scan_uris():
    """Return the list of URIs currently visible to the radio stack.

    With a Crazyradio plugged in this returns every discovered Crazyflie.
    """
    return [uri for uri, _ in cflib.crtp.scan_interfaces()]


def first_available_uri():
    """Pick the first discovered Crazyflie, falling back to the default URI."""
    uris = scan_uris()
    if uris:
        return uris[0]
    return URI


def open_link(uri):
    """Open a blocking connection and return a ready SyncCrazyflie.

    The rw_cache speeds up the (otherwise slow) log/param TOC download.
    """
    cf = Crazyflie(rw_cache=CACHE_DIR)
    return SyncCrazyflie(uri, cf=cf)


def wait_for_params(scf):
    """Block until parameter values finished downloading after connect."""
    scf.wait_for_params()
