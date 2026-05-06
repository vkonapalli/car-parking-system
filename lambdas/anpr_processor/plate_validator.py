import re

NZ_PLATE_PATTERNS = [
    re.compile(r"^[A-Z]{3}\d{3}$"),       # ABC123 (standard)
    re.compile(r"^[A-Z]{2}\d{4}$"),        # AB1234
    re.compile(r"^[A-Z]{3}\d{2}$"),        # ABC12 (older)
    re.compile(r"^[A-Z]{2}\d{3}$"),        # AB123 (older)
    re.compile(r"^[A-Z]{1}\d{4,5}$"),      # A1234, A12345
    re.compile(r"^[A-Z]{3}\d{3}[A-Z]$"),   # ABC123D (trailer)
    re.compile(r"^[A-Z0-9]{1,7}$"),        # personalised (loose catch-all)
]


def clean_plate(raw_text: str) -> str:
    """Strip non-alphanumeric characters and uppercase."""
    return re.sub(r"[^A-Z0-9]", "", raw_text.upper())


def validate_nz_plate(text: str) -> bool:
    """Check if text matches a known NZ plate format."""
    cleaned = clean_plate(text)
    if len(cleaned) < 2 or len(cleaned) > 7:
        return False
    return any(p.match(cleaned) for p in NZ_PLATE_PATTERNS[:-1])


def process_plate(raw_text: str, ocr_confidence: float) -> tuple[str | None, float]:
    """Clean OCR output and validate against NZ plate formats.

    Returns (rego, adjusted_confidence). If the plate doesn't match any
    NZ format, confidence is penalised. Returns None if input is empty.
    """
    cleaned = clean_plate(raw_text)
    if not cleaned:
        return None, 0.0

    if validate_nz_plate(cleaned):
        return cleaned, ocr_confidence

    confidence_penalty = 0.3
    return cleaned, max(0.0, ocr_confidence - confidence_penalty)
