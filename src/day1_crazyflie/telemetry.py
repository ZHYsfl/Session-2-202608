"""Real-time telemetry subscription for the Crazyflie.

Subscribes to the state-estimate and battery log groups and keeps a shared,
thread-safe snapshot that other modules (and the virtual-fence watchdog) can
poll. Optionally streams every sample to a CSV file for the day-1 write-up.
"""
import csv
import threading

from cflib.crazyflie.log import LogConfig

# Telemetry variables we care about:
#   position (m), velocity (m/s), attitude (deg) and battery (V).
TELEMETRY_VARS = (
    'stateEstimate.x',
    'stateEstimate.y',
    'stateEstimate.z',
    'stateEstimate.vx',
    'stateEstimate.vy',
    'stateEstimate.vz',
    'stateEstimate.roll',
    'stateEstimate.pitch',
    'stateEstimate.yaw',
    'pm.vbat',
)


class Telemetry:
    """Subscribes to telemetry and keeps the latest snapshot in .latest."""

    def __init__(self, cf, period_ms=50, csv_path=None):
        self._cf = cf
        self.period_ms = period_ms
        self.latest = {}          # {var: value} of the newest received sample
        self._lock = threading.Lock()
        self._logconf = None
        self._csv_file = None
        self._csv_writer = None

        if csv_path:
            self._csv_file = open(csv_path, 'w', newline='', encoding='utf-8')
            self._csv_writer = csv.DictWriter(
                self._csv_file, fieldnames=('timestamp',) + TELEMETRY_VARS)
            self._csv_writer.writeheader()

    def start(self):
        self._logconf = LogConfig(name='Day1Telemetry', period_in_ms=self.period_ms)
        for var in TELEMETRY_VARS:
            self._logconf.add_variable(var, 'float')
        self._logconf.data_received_cb.add_callback(self._on_data)
        self._cf.log.add_config(self._logconf)
        self._logconf.start()

    def _on_data(self, timestamp, data, logconf):
        row = {'timestamp': timestamp}
        row.update(data)
        with self._lock:
            self.latest = dict(data)
        if self._csv_writer is not None:
            self._csv_writer.writerow(row)

    def get(self, var, default=None):
        """Thread-safe read of one telemetry variable."""
        with self._lock:
            return self.latest.get(var, default)

    def stop(self):
        if self._logconf is not None:
            self._logconf.stop()
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
