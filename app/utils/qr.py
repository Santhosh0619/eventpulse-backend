"""QR code generation (qrcode + Pillow)."""

import io

import qrcode


def generate_qr_png(payload: str) -> bytes:
    """Return PNG bytes encoding ``payload`` as a QR code."""
    img = qrcode.make(payload)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
