"""ESP32 MJPEG fetcher (direct from the camera, no MediaMTX dependency).

Polls the ESP32's `/stream` endpoint, extracts JPEG frames from the MJPEG
multipart stream, and exposes the latest frame to the GUI.
"""

import threading
import time
import urllib.request


class MjpegFetcher(threading.Thread):
    def __init__(self, url="http://10.219.80.107/stream"):
        super().__init__(daemon=True)
        self._url = url
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._connected = False

    def run(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(
                    self._url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "*/*",
                    },
                )
                with opener.open(req, timeout=8) as resp:
                    self._set_connected(True)
                    buf = bytearray()
                    while not self._stop.is_set():
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        buf.extend(chunk)
                        # Extract complete JPEG frames (SOI..EOI markers)
                        while True:
                            soi = buf.find(b"\xff\xd8")
                            if soi < 0:
                                break
                            eoi = buf.find(b"\xff\xd9", soi + 2)
                            if eoi < 0:
                                break
                            frame = bytes(buf[soi : eoi + 2])
                            with self._lock:
                                self._frame = frame
                            buf = bytearray(buf[eoi + 2 :])
            except Exception:
                self._set_connected(False)
            if not self._stop.is_set():
                time.sleep(2)

    def latest(self):
        with self._lock:
            return self._frame

    def connected(self):
        with self._lock:
            return self._connected

    def set_url(self, url):
        self._url = url

    def restart(self):
        """Stop and start a fresh thread (call after changing the URL)."""
        self._stop.set()
        if self.is_alive():
            self.join(timeout=3)
        self._stop.clear()
        with self._lock:
            self._frame = None
            self._connected = False
        self.start()

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=3)

    def _set_connected(self, value):
        with self._lock:
            self._connected = value
