from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_superadmin_connection

router = APIRouter(prefix="/aplicativos", tags=["aplicativos"])

# Los mismos 4 aplicativos que lista la página Aplicativos del front del cliente.
APP_KEYS = ("domiciliario", "mesero", "escritorio", "driver")


class IconosAplicativosOut(BaseModel):
    iconos: dict[str, str] = {}


@router.get("/iconos", response_model=IconosAplicativosOut)
def iconos_aplicativos():
    """Un icono por aplicativo (el que subió el SuperAdmin en su pestaña Apps), para la página
    pública de Aplicativos. Pública: no requiere sesión. Si el panel del SuperAdmin no responde,
    se devuelve vacío y el front se queda con su icono genérico de respaldo."""
    try:
        conn = get_superadmin_connection()
    except Exception:
        return IconosAplicativosOut()
    try:
        resultado: dict[str, str] = {}
        for key in APP_KEYS:
            rows = conn.run(
                "SELECT imagen FROM app_iconos WHERE app_key = :k "
                "ORDER BY (plataforma = 'todas') DESC, created_at DESC LIMIT 1",
                k=key,
            )
            if rows:
                resultado[key] = rows[0][0]
        return IconosAplicativosOut(iconos=resultado)
    except Exception:
        return IconosAplicativosOut()
    finally:
        conn.close()
