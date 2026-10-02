from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_superadmin_connection

router = APIRouter(prefix="/apariencias", tags=["apariencias"])

APARIENCIAS_VALIDAS = {"violet-original", "halloween", "navidad"}
DEFAULT = "violet-original"


class AparienciaLoginOut(BaseModel):
    apariencia: str = DEFAULT


@router.get("/login", response_model=AparienciaLoginOut)
def apariencia_login():
    """Apariencia que el SuperAdmin eligió para la pantalla de inicio de sesión. Pública: se lee antes de entrar.
    Si el panel del SuperAdmin no responde, se usa la apariencia por defecto."""
    try:
        conn = get_superadmin_connection()
    except Exception:
        return AparienciaLoginOut()
    try:
        rows = conn.run("SELECT apariencia_key FROM apariencia_login WHERE id = 1")
        clave = rows[0][0] if rows else DEFAULT
        return AparienciaLoginOut(apariencia=clave if clave in APARIENCIAS_VALIDAS else DEFAULT)
    except Exception:
        return AparienciaLoginOut()
    finally:
        conn.close()
