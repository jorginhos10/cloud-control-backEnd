from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import UserOut, get_current_user
from app.database import get_superadmin_connection

router = APIRouter(prefix="/chat-soporte", tags=["chat-soporte"])

MENSAJE_COLUMNS = ["id", "comercio_id", "de", "mensaje", "created_at"]


class ChatSoporteResumenOut(BaseModel):
    ultimo_mensaje: Optional[str] = None
    ultimo_mensaje_de: Optional[str] = None
    ultimo_mensaje_at: Optional[datetime] = None
    no_leidos: int


class ChatSoporteMensajeOut(BaseModel):
    id: int
    comercio_id: int
    de: str
    mensaje: str
    created_at: datetime


class ChatSoporteMensajeIn(BaseModel):
    mensaje: str


@router.get("/resumen", response_model=ChatSoporteResumenOut)
def resumen(current_user: UserOut = Depends(get_current_user)):
    conn = get_superadmin_connection()
    try:
        rows = conn.run(
            "SELECT mensaje, de, created_at FROM chat_soporte_mensajes "
            "WHERE comercio_id = :cid ORDER BY created_at DESC LIMIT 1",
            cid=current_user.tenant_id,
        )
        no_leidos_rows = conn.run(
            "SELECT COUNT(*) FROM chat_soporte_mensajes "
            "WHERE comercio_id = :cid AND de = 'superadmin' AND leido_comercio = false",
            cid=current_user.tenant_id,
        )
        ultimo = rows[0] if rows else None
        return ChatSoporteResumenOut(
            ultimo_mensaje=ultimo[0] if ultimo else None,
            ultimo_mensaje_de=ultimo[1] if ultimo else None,
            ultimo_mensaje_at=ultimo[2] if ultimo else None,
            no_leidos=no_leidos_rows[0][0],
        )
    finally:
        conn.close()


@router.get("/mensajes", response_model=list[ChatSoporteMensajeOut])
def listar_mensajes(current_user: UserOut = Depends(get_current_user)):
    conn = get_superadmin_connection()
    try:
        conn.run(
            "UPDATE chat_soporte_mensajes SET leido_comercio = true "
            "WHERE comercio_id = :cid AND de = 'superadmin'",
            cid=current_user.tenant_id,
        )
        rows = conn.run(
            f"SELECT {', '.join(MENSAJE_COLUMNS)} FROM chat_soporte_mensajes "
            "WHERE comercio_id = :cid ORDER BY created_at",
            cid=current_user.tenant_id,
        )
        return [ChatSoporteMensajeOut(**dict(zip(MENSAJE_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("/mensajes", response_model=ChatSoporteMensajeOut, status_code=201)
def enviar_mensaje(payload: ChatSoporteMensajeIn, current_user: UserOut = Depends(get_current_user)):
    texto = payload.mensaje.strip()
    conn = get_superadmin_connection()
    try:
        rows = conn.run(
            f"INSERT INTO chat_soporte_mensajes (comercio_id, de, mensaje, leido_superadmin) "
            f"VALUES (:cid, 'comercio', :msg, false) RETURNING {', '.join(MENSAJE_COLUMNS)}",
            cid=current_user.tenant_id, msg=texto,
        )
        return ChatSoporteMensajeOut(**dict(zip(MENSAJE_COLUMNS, rows[0])))
    finally:
        conn.close()
