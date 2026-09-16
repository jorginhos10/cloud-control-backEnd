from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import NegocioIn, NegocioOut

router = APIRouter(prefix="/negocio", dependencies=[Depends(get_current_user)])

NEGOCIO_EDIT_COLUMNS = [
    "nombre", "tipo", "moneda", "eslogan", "horario_apertura", "horario_cierre",
    "rut", "direccion", "ciudad", "telefono", "email", "sitio_web", "logo_url",
]
NEGOCIO_COLUMNS = NEGOCIO_EDIT_COLUMNS + ["updated_at"]


def _negocio_por_defecto() -> NegocioOut:
    return NegocioOut(updated_at=datetime.now(timezone.utc))


@router.get("", response_model=NegocioOut)
def get_negocio(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(NEGOCIO_COLUMNS)} FROM negocios WHERE usuario_id = :id",
            id=current_user.tenant_id,
        )
        if not rows:
            return _negocio_por_defecto()
        return NegocioOut(**dict(zip(NEGOCIO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("", response_model=NegocioOut)
def guardar_negocio(payload: NegocioIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"""
            INSERT INTO negocios (usuario_id, {', '.join(NEGOCIO_EDIT_COLUMNS)})
            VALUES (:uid, :nombre, :tipo, :moneda, :eslogan, :horario_apertura, :horario_cierre,
                    :rut, :direccion, :ciudad, :telefono, :email, :sitio_web, :logo_url)
            ON CONFLICT (usuario_id) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                tipo = EXCLUDED.tipo,
                moneda = EXCLUDED.moneda,
                eslogan = EXCLUDED.eslogan,
                horario_apertura = EXCLUDED.horario_apertura,
                horario_cierre = EXCLUDED.horario_cierre,
                rut = EXCLUDED.rut,
                direccion = EXCLUDED.direccion,
                ciudad = EXCLUDED.ciudad,
                telefono = EXCLUDED.telefono,
                email = EXCLUDED.email,
                sitio_web = EXCLUDED.sitio_web,
                logo_url = EXCLUDED.logo_url,
                updated_at = now()
            RETURNING {', '.join(NEGOCIO_COLUMNS)}
            """,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            tipo=payload.tipo,
            moneda=payload.moneda,
            eslogan=payload.eslogan.strip(),
            horario_apertura=payload.horario_apertura,
            horario_cierre=payload.horario_cierre,
            rut=payload.rut.strip(),
            direccion=payload.direccion.strip(),
            ciudad=payload.ciudad.strip(),
            telefono=payload.telefono.strip(),
            email=payload.email.strip(),
            sitio_web=payload.sitio_web.strip(),
            logo_url=payload.logo_url,
        )
        return NegocioOut(**dict(zip(NEGOCIO_COLUMNS, rows[0])))
    finally:
        conn.close()
