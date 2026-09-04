from fastapi import APIRouter, Request

from app import wompi
from app.database import get_connection

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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

    return {"ok": True}
