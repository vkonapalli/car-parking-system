import cv2
import numpy as np


def detect_plate(image_bytes: bytes) -> bytes | None:
    """Detect and crop the licence plate region from a car image.

    Returns the cropped plate image as JPEG bytes, or None if no plate found.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(gray, 30, 200)

    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]

    img_h, img_w = img.shape[:2]
    img_area = img_h * img_w
    best = None
    best_area = 0

    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

        if len(approx) != 4:
            continue

        x, y, w, h = cv2.boundingRect(approx)
        aspect_ratio = w / h if h > 0 else 0
        area = w * h
        area_ratio = area / img_area

        # NZ plates are roughly 3:1 to 5:1 aspect ratio
        if 2.0 <= aspect_ratio <= 6.0 and area_ratio > 0.005 and area > best_area:
            best = (x, y, w, h)
            best_area = area

    if best is None:
        return _fallback_crop(img)

    x, y, w, h = best
    pad_x = int(w * 0.05)
    pad_y = int(h * 0.1)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(img_w, x + w + pad_x)
    y2 = min(img_h, y + h + pad_y)

    cropped = img[y1:y2, x1:x2]
    _, buf = cv2.imencode(".jpg", cropped)
    return buf.tobytes()


def _fallback_crop(img: np.ndarray) -> bytes | None:
    """If contour detection fails, crop the lower-center of the image where plates typically are."""
    h, w = img.shape[:2]
    y1 = int(h * 0.55)
    y2 = int(h * 0.85)
    x1 = int(w * 0.2)
    x2 = int(w * 0.8)
    cropped = img[y1:y2, x1:x2]
    if cropped.size == 0:
        return None
    _, buf = cv2.imencode(".jpg", cropped)
    return buf.tobytes()
