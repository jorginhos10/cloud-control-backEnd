from fastapi import APIRouter, Request

from app import wompi
from app.database import get_connection

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _procesar_pedido_marketplace(reference: str, transaction_id: str, nuevo_estado: str) -> None:
    conn = get_connection()
    try:
        conn.run(
            "UPDATE marketplace_pedidos "
            "SET estado = :estado, wompi_transaction_id = :tid, updated_at = now() "
            "WHERE wompi_reference = :ref",
            estado=nuevo_estado, tid=transaction_id, ref=reference,
        )
    finally:
        conn.close()


def _procesar_pago_suscripcion(reference: str, transaction_id: str, nuevo_estado: str) -> None:
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT usuario_id, plan_id, estado FROM suscripcion_pagos WHERE wompi_reference = :ref",
            ref=reference,
        )
        if not rows:
            return
        usuario_id, plan_id, estado_previo = rows[0]

        conn.run(
            "UPDATE suscripcion_pagos SET estado = :estado, wompi_transaction_id = :tid, updated_at = now() "
            "WHERE wompi_reference = :ref",
            estado=nuevo_estado, tid=transaction_id, ref=reference,
        )

        if nuevo_estado == "pagado" and estado_previo != "pagado":
            conn.run(
                "UPDATE usuarios SET plan_id = :pid, plan_actualizado_en = now() WHERE id = :id",
                pid=plan_id, id=usuario_id,
            )
    finally:
        conn.close()


@router.post("/wompi")
async def wompi_webhook(request: Request):
    """Public endpoint — Wompi calls this server-to-server, never a browser.
    No user auth applies here; the event's own checksum (signed with our
    events secret) is what proves it really came from Wompi."""
    event = await request.json()

    if not wompi.verify_event_checksum(event):
        return {"ok": False}

    if event.get("event") != "transaction.updated":
        return {"ok": True}

    transaction = event.get("data", {}).get("transaction", {})
    reference = transaction.get("reference")
    transaction_id = transaction.get("id")
    nuevo_estado = wompi.STATUS_MAP.get(transaction.get("status"), "pendiente_pago")

    if not reference:
        return {"ok": True}

    if reference.startswith("sus-"):
        _procesar_pago_suscripcion(reference, transaction_id, nuevo_estado)
    else:
        _procesar_pedido_marketplace(reference, transaction_id, nuevo_estado)

    return {"ok": True}
