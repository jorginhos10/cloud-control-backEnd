import base64
import io

from PIL import Image

THUMB_MAX_DIM = 100
THUMB_QUALITY = 55


def generar_thumbnail(data_url: str | None) -> str | None:
    """Reduce una foto (guardada como data URL base64) a una miniatura liviana para listados.
    Las fotos de producto/topping llegan ya comprimidas a ~640px/320px por el navegador, pero
    eso sigue siendo demasiado para un listado con decenas de productos: cada GET /recetas
    terminaba arrastrando varios MB de base64 solo para pintar thumbnails de 48px. Esta miniatura
    es la que se usa en los listados; el data_url original se sigue guardando para el detalle."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        _, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded)
        imagen = Image.open(io.BytesIO(raw))
        imagen = imagen.convert("RGB")
        imagen.thumbnail((THUMB_MAX_DIM, THUMB_MAX_DIM))
        buffer = io.BytesIO()
        imagen.save(buffer, format="JPEG", quality=THUMB_QUALITY)
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except Exception:
        return None
