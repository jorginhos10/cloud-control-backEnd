from fastapi import APIRouter, Depends

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import ConfiguracionImpresionIn, ConfiguracionImpresionOut

router = APIRouter(prefix="/configuracion", tags=["configuracion"], dependencies=[Depends(get_current_user)])


@router.get("/impresion", response_model=ConfiguracionImpresionOut)
def obtener_impresion(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT modo_impresion_comanda, tamano_papel_comanda FROM usuarios WHERE id = :id",
            id=current_user.tenant_id,
        )
        return ConfiguracionImpresionOut(modo_impresion_comanda=rows[0][0], tamano_papel_comanda=rows[0][1])
    finally:
        conn.close()


@router.put("/impresion", response_model=ConfiguracionImpresionOut)
def actualizar_impresion(payload: ConfiguracionImpresionIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        conn.run(
            "UPDATE usuarios SET modo_impresion_comanda = :modo, tamano_papel_comanda = :papel WHERE id = :id",
            modo=payload.modo_impresion_comanda,
            papel=payload.tamano_papel_comanda,
            id=current_user.tenant_id,
        )
        return ConfiguracionImpresionOut(
            modo_impresion_comanda=payload.modo_impresion_comanda,
            tamano_papel_comanda=payload.tamano_papel_comanda,
        )
    finally:
        conn.close()
