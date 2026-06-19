"""Wstępne przetwarzanie obrazu przed OCR.

Najważniejszy dla słabych skanów (kserokopie, zdjęcia telefonem):
- deskew (prostowanie przekrzywienia) metodą Hough Lines, odporny
  na artefakty kserokopiarki,
- konwersja do skali szarości,
- delikatne podbicie kontrastu.

Wszystkie kroki są opcjonalne i sterowane parametrami, bo dla czystych
skanów cyfrowych potrafią zaszkodzić.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def _deskew(gray: np.ndarray) -> float:
    """Zwraca kąt przekrzywienia w stopniach (Hough Lines)."""
    import cv2

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    if lines is None:
        return 0.0

    angles = []
    for rho_theta in lines[:200]:
        _, theta = rho_theta[0]
        deg = np.degrees(theta) - 90.0
        if -45 < deg < 45:  # ignorujemy linie pionowe
            angles.append(deg)

    if not angles:
        return 0.0
    return float(np.median(angles))


def preprocess(
    image_bytes: bytes,
    *,
    deskew: bool = True,
    grayscale: bool = True,
    enhance_contrast: bool = True,
) -> bytes:
    """Przetwarza obraz i zwraca go jako PNG (bytes).

    Domyślnie wszystkie kroki włączone — dobre dla trudnych skanów.
    Dla czystych dokumentów cyfrowych warto wyłączyć deskew.
    """
    import cv2

    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    if deskew:
        angle = _deskew(gray)
        if abs(angle) > 0.3:  # prostujemy tylko realne przekrzywienia
            h, w = gray.shape
            center = (w // 2, h // 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            arr = cv2.warpAffine(
                arr, matrix, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    if enhance_contrast:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

    out_arr = gray if grayscale else arr
    out_pil = Image.fromarray(out_arr)

    buf = io.BytesIO()
    out_pil.save(buf, format="PNG")
    return buf.getvalue()
