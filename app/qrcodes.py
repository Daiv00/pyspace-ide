"""Серверная генерация QR-кодов (PNG и SVG) — браузеру ничего качать не нужно."""

from __future__ import annotations

import io

import qrcode
from qrcode.image.svg import SvgPathImage


def png(url: str, box_size: int = 10, border: int = 2) -> io.BytesIO:
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="#0b0d12", back_color="#ffffff")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def svg(url: str) -> bytes:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()
