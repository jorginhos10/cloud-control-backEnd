from fastapi import APIRouter, HTTPException, status

from app.database import get_connection
from app.schemas import PqrsIn, PqrsValidoOut

router = APIRouter(prefix="/pqrs-publico")


def _resolver_usuario(conn, token: str) -> int:
    rows = conn.run("SELECT id FROM usuarios WHERE pqrs_token = :t", t=token)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no encontrado")
    return rows[0][0]


@router.get("/{token}", response_model=PqrsValidoOut)
def verificar(token: str):
    conn = get_connection()
    try:
        _resolver_usuario(conn, token)
        return PqrsValidoOut(valido=True)
    finally:
        conn.close()


@router.post("/{token}/enviar", status_code=status.HTTP_201_CREATED)
def enviar(token: str, payload: PqrsIn):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        conn.run(
            "INSERT INTO pqrs (usuario_id, nombre, email, telefono, tipo, calificacion, mensaje) "
            "VALUES (:uid, :nombre, :email, :telefono, :tipo, :calif, :mensaje)",
            uid=usuario_id,
            nombre=payload.nombre.strip(),
            email=payload.email.strip() or None,
            telefono=payload.telefono.strip() or None,
            tipo=payload.tipo,
            calif=payload.calificacion,
            mensaje=payload.mensaje.strip(),
        )
        return {"success": True}
    finally:
        conn.close()
