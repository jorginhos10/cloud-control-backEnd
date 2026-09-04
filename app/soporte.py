from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import UserOut, get_current_user
from app.database import get_superadmin_connection

router = APIRouter(prefix="/soporte", tags=["soporte"])


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
    created_at: datetime


class SoporteTicketIn(BaseModel):
    asunto: str
    mensaje: str


class SoporteMensajeIn(BaseModel):
    mensaje: str


TICKET_COLUMNS = ["id", "asunto", "estado", "no_leidos_comercio", "created_at", "updated_at"]
MENSAJE_COLUMNS = ["id", "ticket_id", "de", "mensaje", "created_at"]


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
    if not asunto or not mensaje:
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
            "INSERT INTO soporte_mensajes (ticket_id, de, mensaje) VALUES (:tid, 'comercio', :msg)",
            tid=ticket["id"], msg=mensaje,
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
    if not texto:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El mensaje no puede estar vacío")

    conn = get_superadmin_connection()
    try:
        _get_ticket_or_404(conn, current_user.tenant_id, ticket_id)
        rows = conn.run(
            f"INSERT INTO soporte_mensajes (ticket_id, de, mensaje) VALUES (:tid, 'comercio', :msg) "
            f"RETURNING {', '.join(MENSAJE_COLUMNS)}",
            tid=ticket_id, msg=texto,
        )
        conn.run(
            "UPDATE soporte_tickets SET updated_at = now(), no_leidos_superadmin = no_leidos_superadmin + 1, "
            "estado = CASE WHEN estado = 'cerrado' THEN 'en_progreso' ELSE estado END WHERE id = :id",
            id=ticket_id,
        )
        return SoporteMensajeOut(**dict(zip(MENSAJE_COLUMNS, rows[0])))
    finally:
        conn.close()
