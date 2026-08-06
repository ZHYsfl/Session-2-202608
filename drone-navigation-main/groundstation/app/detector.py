"""Local YOLO person detector (runs on the ground station machine).

Pulls the latest camera frame, runs YOLOv8 inference with ultralytics, and
returns a JSON-friendly summary plus an annotated JPEG.  The model is
loaded lazily on first use so the GUI stays fast to start.
"""

import base64
import os
import threading

import cv2
import numpy as np

MODEL_CANDIDATES = (
    os.environ.get("YOLO_MODEL", ""),
    os.path.expanduser("~/yolov8n.pt"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "yolov8n.pt"),
    "yolov8n.pt",
)

PERSON_CLASS = 0  # COCO: person


class YoloDetector:
    """Thread-safe YOLO detector wrapper."""

    def __init__(self, model_path=None, conf=0.4):
        self._model_path = model_path or next(
            (p for p in MODEL_CANDIDATES if p and os.path.exists(p)), None
        )
        self._conf = conf
        self._model = None
        self._lock = threading.Lock()

    def available(self):
        return self._model_path is not None

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from ultralytics import YOLO

                self._model = YOLO(self._model_path)
        return self._model

    def detect(self, frame_jpeg, conf=None):
        """Detect persons in a JPEG frame.

        Returns:
            dict with keys: ok, count, persons (list of {bbox, confidence}),
            annotated_jpeg (bytes, image with boxes drawn), error (optional)
        """
        if not frame_jpeg:
            return {"ok": False, "error": "no frame"}
        if not self.available():
            return {
                "ok": False,
                "error": "YOLO model not found (set YOLO_MODEL or place yolov8n.pt in ~/)",
            }
        model = self._load()
        nparr = np.frombuffer(frame_jpeg, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"ok": False, "error": "failed to decode frame"}

        results = model.predict(
            img,
            conf=self._conf if conf is None else conf,
            verbose=False,
        )
        persons = []
        for r in results:
            for box in r.boxes:
                cls = int(box.cls.item())
                if cls != PERSON_CLASS:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                persons.append(
                    {
                        "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                        "confidence": round(float(box.conf.item()), 3),
                    }
                )

        annotated = None
        if persons and results:
            plot = results[0].plot(line_width=2)
            ok, buf = cv2.imencode(".jpg", plot, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                annotated = buf.tobytes()

        return {
            "ok": True,
            "count": len(persons),
            "persons": persons,
            "annotated_jpeg": annotated,
        }

    def detect_b64(self, frame_jpeg, conf=None):
        """Like :meth:`detect` but returns annotated image as base64 text."""
        res = self.detect(frame_jpeg, conf=conf)
        if res.get("annotated_jpeg"):
            res["annotated_b64"] = base64.b64encode(res["annotated_jpeg"]).decode("ascii")
            res["annotated_jpeg"] = None  # keep the JSON payload small
        return res

    # ------------------------------------------------------------------ #
    # Color-based detection (no model required)
    # ------------------------------------------------------------------ #

    _HSV_RANGES = {
        "red": [
            ((0, 100, 60), (10, 255, 255)),
            ((170, 100, 60), (180, 255, 255)),
        ],
        "green": [
            ((40, 60, 60), (85, 255, 255)),
        ],
        "blue": [
            ((95, 100, 60), (130, 255, 255)),
        ],
    }

    def detect_color(self, frame_jpeg, color="red", min_area_ratio=0.005):
        """Detect colored regions (e.g. red blocks) via HSV segmentation.

        No YOLO model needed — pure OpenCV, runs in milliseconds.
        Returns: ok, color, count, regions ([{bbox, area, area_ratio}]),
        annotated_jpeg (image with boxes drawn).
        """
        if not frame_jpeg:
            return {"ok": False, "error": "no frame"}
        nparr = np.frombuffer(frame_jpeg, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"ok": False, "error": "failed to decode frame"}

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        ranges = self._HSV_RANGES.get(color)
        if not ranges:
            return {
                "ok": False,
                "error": f"unsupported color '{color}' (supported: {list(self._HSV_RANGES)})",
            }

        mask = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, lo, hi)
            mask = part if mask is None else cv2.bitwise_or(mask, part)
        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)

        h, w = img.shape[:2]
        min_area = max(20, int(w * h * min_area_ratio))
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        regions = []
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            regions.append(
                {
                    "bbox": [x, y, x + bw, y + bh],
                    "area": round(area, 1),
                    "area_ratio": round(area / (w * h), 4),
                }
            )

        annotated = None
        if regions:
            draw = img.copy()
            for r in regions:
                x1, y1, x2, y2 = r["bbox"]
                cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    draw,
                    f"{color} {r['area_ratio']:.1%}",
                    (x1, max(14, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 255, 0),
                    1,
                )
            ok, buf = cv2.imencode(".jpg", draw, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                annotated = buf.tobytes()

        return {
            "ok": True,
            "color": color,
            "count": len(regions),
            "regions": regions,
            "annotated_jpeg": annotated,
        }
