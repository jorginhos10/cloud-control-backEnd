import base64
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import UserOut, get_current_user
from app.database import get_superadmin_connection

router = APIRouter(prefix="/soporte", tags=["soporte"])

MAX_IMAGEN_BYTES = 5 * 1024 * 1024
IMAGEN_DATA_URL = re.compile(r"^data:image/(png|jpe?g|gif|webp);base64,")


def _validar_imagen(imagen_url: Optional[str]) -> Optional[str]:
    if imagen_url is None:
        return None
    if not IMAGEN_DATA_URL.match(imagen_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen debe ser PNG, JPG, GIF o WEBP")
    b64 = imagen_url.split(",", 1)[1]
    try:
        contenido = base64.b64decode(b64, validate=True)
    except (ValueError, base64.binascii.Error):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen está dañada")
    if len(contenido) > MAX_IMAGEN_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen no puede pesar más de 5 MB")
    return imagen_url


class SoporteTicketOut(BaseModel):
    id: int
    asunto: str
    estado: str
    no_leidos_comercio: int
    created_at: datetime
    updated_at: datetime


class SoporteMensajeOut(BaseModel):
    id: int
    ticket_id: int
    de: str
    mensaje: str
    imagen_url: Optional[str] = None
    created_at: datetime


class SoporteTicketIn(BaseModel):
    asunto: str
    mensaje: str = ""
    imagen_url: Optional[str] = None


class SoporteMensajeIn(BaseModel):
    mensaje: str = ""
    imagen_url: Optional[str] = None


TICKET_COLUMNS = ["id", "asunto", "estado", "no_leidos_comercio", "created_at", "updated_at"]
MENSAJE_COLUMNS = ["id", "ticket_id", "de", "mensaje", "imagen_url", "created_at"]


def _get_ticket_or_404(conn, comercio_id: int, ticket_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(TICKET_COLUMNS)} FROM soporte_tickets WHERE id = :id AND comercio_id = :cid",
        id=ticket_id, cid=comercio_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado")
    return dict(zip(TICKET_COLUMNS, rows[0]))


@router.get("/tickets", response_model=list[SoporteTicketOut])
def listar_tickets(current_user: UserOut = Depends(get_current_user)):
    conn = get_superadmin_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(TICKET_COLUMNS)} FROM soporte_tickets WHERE comercio_id = :cid ORDER BY updated_at DESC",
            cid=current_user.tenant_id,
        )
        return [SoporteTicketOut(**dict(zip(TICKET_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("/tickets", response_model=SoporteTicketOut, status_code=status.HTTP_201_CREATED)
def crear_ticket(payload: SoporteTicketIn, current_user: UserOut = Depends(get_current_user)):
    asunto = payload.asunto.strip()
    mensaje = payload.mensaje.strip()
    imagen_url = _validar_imagen(payload.imagen_url)
    if not asunto or (not mensaje and not imagen_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Asunto y mensaje son obligatorios")

    conn = get_superadmin_connection()
    try:
        rows = conn.run(
            f"INSERT INTO soporte_tickets (comercio_id, asunto, no_leidos_superadmin) "
            f"VALUES (:cid, :asunto, 1) RETURNING {', '.join(TICKET_COLUMNS)}",
            cid=current_user.tenant_id, asunto=asunto,
        )
        ticket = dict(zip(TICKET_COLUMNS, rows[0]))
        conn.run(
            "INSERT INTO soporte_mensajes (ticket_id, de, mensaje, imagen_url) VALUES (:tid, 'comercio', :msg, :img)",
            tid=ticket["id"], msg=mensaje, img=imagen_url,
        )
        return SoporteTicketOut(**ticket)
    finally:
        conn.close()


@router.get("/tickets/{ticket_id}/mensajes", response_model=list[SoporteMensajeOut])
def listar_mensajes(ticket_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_superadmin_connection()
    try:
        _get_ticket_or_404(conn, current_user.tenant_id, ticket_id)
        conn.run("UPDATE soporte_tickets SET no_leidos_comercio = 0 WHERE id = :id", id=ticket_id)
        rows = conn.run(
            f"SELECT {', '.join(MENSAJE_COLUMNS)} FROM soporte_mensajes "
            "WHERE ticket_id = :id ORDER BY created_at",
            id=ticket_id,
        )
        return [SoporteMensajeOut(**dict(zip(MENSAJE_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/mensajes", response_model=SoporteMensajeOut, status_code=status.HTTP_201_CREATED)
def enviar_mensaje(ticket_id: int, payload: SoporteMensajeIn, current_user: UserOut = Depends(get_current_user)):
    texto = payload.mensaje.strip()
    imagen_url = _validar_imagen(payload.imagen_url)
    if not texto and not imagen_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El mensaje no puede estar vacío")

    conn = get_superadmin_connection()
    try:
        _get_ticket_or_404(conn, current_user.tenant_id, ticket_id)
        rows = conn.run(
            f"INSERT INTO soporte_mensajes (ticket_id, de, mensaje, imagen_url) VALUES (:tid, 'comercio', :msg, :img) "
            f"RETURNING {', '.join(MENSAJE_COLUMNS)}",
            tid=ticket_id, msg=texto, img=imagen_url,
        )
        conn.run(
            "UPDATE soporte_tickets SET updated_at = now(), no_leidos_superadmin = no_leidos_superadmin + 1, "
            "estado = CASE WHEN estado = 'cerrado' THEN 'en_progreso' ELSE estado END WHERE id = :id",
            id=ticket_id,
        )
        return SoporteMensajeOut(**dict(zip(MENSAJE_COLUMNS, rows[0])))
    finally:
        conn.close()
