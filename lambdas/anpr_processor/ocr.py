import cv2
import numpy as np
import pytesseract


def read_plate(plate_image_bytes: bytes) -> tuple[str, float]:
    """OCR a cropped plate image. Returns (raw_text, confidence).

    Confidence is 0.0-1.0 based on Tesseract's mean confidence.
    """
    arr = np.frombuffer(plate_image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return "", 0.0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    data = pytesseract.image_to_data(
        gray,
        config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        output_type=pytesseract.Output.DICT,
    )

    chars = []
    confidences = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if text and int(data["conf"][i]) > 0:
            chars.append(text)
            confidences.append(int(data["conf"][i]))

    raw_text = "".join(chars)
    avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0

    return raw_text, avg_confidence
