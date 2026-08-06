"""ESP32 MJPEG fetcher + background decoder (no MediaMTX dependency).

Polls the ESP32's ``/stream`` endpoint, extracts JPEG frames from the MJPEG
multipart stream, and exposes the latest raw frame.  A :class:`VideoDecoder`
thread performs JPEG decode / scaling OFF the GUI thread so the main window
never blocks on video work.
"""

import threading
import time
import urllib.request

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QTransform

MAX_BUF = 2 * 1024 * 1024  # drop the buffer if it grows this big (corrupt stream)


class MjpegFetcher(threading.Thread):
    def __init__(self, url="http://10.219.80.107/stream"):
        super().__init__(daemon=True)
        self._url = url
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
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
                        # Guard against a corrupt stream that never produces
                        # a complete frame (EOI) and would otherwise grow
                        # without bound.
                        if len(buf) > MAX_BUF:
                            buf = bytearray()
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
                                self._seq += 1
                            buf = bytearray(buf[eoi + 2 :])
            except Exception:
                self._set_connected(False)
            if not self._stop.is_set():
                time.sleep(2)

    def latest(self):
        with self._lock:
            return self._frame

    def latest_with_seq(self):
        """Return ``(seq, frame)`` so consumers can skip unchanged frames."""
        with self._lock:
            return self._seq, self._frame

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
            self._seq = 0
            self._connected = False
        self.start()

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=3)

    def _set_connected(self, value):
        with self._lock:
            self._connected = value


class VideoDecoder(threading.Thread):
    """Decodes and scales the latest frame on a background thread.

    The GUI thread only calls :meth:`latest_image` and converts the result
    with ``QPixmap.fromImage`` (no JPEG decode, no scaling in the UI loop).
    """

    def __init__(self, fetcher, poll_s=0.02):
        super().__init__(daemon=True)
        self._fetcher = fetcher
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._image = None
        self._last_seq = -1
        self._target = QSize()
        self._flip = False

    def set_target_size(self, size):
        with self._lock:
            self._target = QSize(size)

    def set_flip(self, flip):
        with self._lock:
            self._flip = bool(flip)

    def reset(self):
        """Forget the previous frame so a restarted fetcher is decoded again."""
        with self._lock:
            self._last_seq = -1
            self._image = None

    def latest_image(self):
        with self._lock:
            return self._image

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=3)

    def run(self):
        while not self._stop.is_set():
            try:
                seq, frame = self._fetcher.latest_with_seq()
                if frame and seq != self._last_seq:
                    self._last_seq = seq
                    img = QImage.fromData(frame, "JPG")
                    if not img.isNull():
                        with self._lock:
                            target = QSize(self._target)
                            flip = self._flip
                        if target.isValid() and not target.isEmpty():
                            img = img.scaled(
                                target,
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation,
                            )
                        if flip:
                            img = img.transformed(QTransform().rotate(180))
                        with self._lock:
                            self._image = img
            except Exception:
                pass  # decoder never kills the app; next poll retries
            time.sleep(self._poll_s)
