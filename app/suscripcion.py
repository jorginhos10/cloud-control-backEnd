import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app import wompi
from app.auth import UserOut, get_current_user
from app.database import get_connection, get_superadmin_connection
from app.modulos import modulos_de_cuenta
from app.schemas import (
    ConfirmarTransaccionIn,
    PlanPublicoOut,
    SeleccionarPlanIn,
    SuscripcionPagoOut,
    WompiCheckoutOut,
)

router = APIRouter(prefix="/suscripcion", dependencies=[Depends(get_current_user)])

REFERENCE_PREFIX = "sus-"


def _plan_actual_id(current_user: UserOut) -> int | None:
    conn = get_connection()
    try:
        rows = conn.run("SELECT plan_id FROM usuarios WHERE id = :id", id=current_user.tenant_id)
        return rows[0][0] if rows else None
    finally:
        conn.close()


def tipo_de_comercio(tenant_id: int) -> str:
    """'store' or 'restobar', from the type the merchant chose on sign-up (accounts with an older type count as restobar)."""
    conn = get_connection()
    try:
        rows = conn.run("SELECT tipo FROM negocios WHERE usuario_id = :id", id=tenant_id)
        return "store" if rows and rows[0][0] == "Store" else "restobar"
    finally:
        conn.close()


# A plan is offered to a merchant when it is active and, either it is of the merchant's type of commerce and public,
# or the SuperAdmin explicitly assigned it to them (whatever its type).
_PLAN_OFRECIDO = """
    p.activo = true
    AND (
        (p.visibilidad = 'publico' AND p.tipo_comercio = :tipo)
        OR EXISTS (SELECT 1 FROM plan_comercios pc WHERE pc.plan_id = p.id AND pc.comercio_id = :tid)
    )
"""


def _fetch_plan_disponible(sconn, plan_id: int, tenant_id: int):
    """A plan this tenant is actually allowed to pick (see _PLAN_OFRECIDO)."""
    rows = sconn.run(
        f"""
        SELECT p.id, p.nombre, p.slug, p.descripcion, p.precio, p.periodo, p.color, p.caracteristicas, p.destacado
        FROM planes p
        WHERE p.id = :id AND {_PLAN_OFRECIDO}
        """,
        id=plan_id, tid=tenant_id, tipo=tipo_de_comercio(tenant_id),
    )
    return rows[0] if rows else None


def _fetch_plan_by_id(sconn, plan_id: int):
    rows = sconn.run(
        "SELECT id, nombre, slug, descripcion, precio, periodo, color, caracteristicas, destacado "
        "FROM planes WHERE id = :id",
        id=plan_id,
    )
    return rows[0] if rows else None


def _plan_publico_out(r, actual: bool) -> PlanPublicoOut:
    return PlanPublicoOut(
        id=r[0], nombre=r[1], slug=r[2], descripcion=r[3], precio=float(r[4]),
        periodo=r[5], color=r[6], caracteristicas=r[7], destacado=r[8], actual=actual,
    )


def _aplicar_plan(tenant_id: int, plan_id: int) -> None:
    conn = get_connection()
    try:
        conn.run(
            "UPDATE usuarios SET plan_id = :pid, plan_actualizado_en = now() WHERE id = :id",
            pid=plan_id, id=tenant_id,
        )
    finally:
        conn.close()


def listar_planes_disponibles(tenant_id: int, plan_marcado: int | None) -> list[PlanPublicoOut]:
    """Plans curated by the SuperAdmin, read-only from here — the public active
    plans of this merchant's type of commerce (Store or Restobar), plus any plan
    explicitly assigned to this merchant.
    `plan_marcado` is the one flagged as `actual` in the result."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return []

    try:
        rows = sconn.run(
            f"""
            SELECT p.id, p.nombre, p.slug, p.descripcion, p.precio, p.periodo, p.color, p.caracteristicas, p.destacado
            FROM planes p
            WHERE {_PLAN_OFRECIDO}
            ORDER BY p.orden ASC, p.id ASC
            """,
            tid=tenant_id, tipo=tipo_de_comercio(tenant_id),
        )
        return [_plan_publico_out(r, actual=(r[0] == plan_marcado)) for r in rows]
    finally:
        sconn.close()


@router.get("/modulos")
def modulos_del_plan(current_user: UserOut = Depends(get_current_user)):
    """Modules the account's plan includes (the client hides and blocks everything else)."""
    return {"modulos": sorted(modulos_de_cuenta(current_user.tenant_id))}


@router.get("/planes", response_model=list[PlanPublicoOut])
def planes(current_user: UserOut = Depends(get_current_user)):
    return listar_planes_disponibles(current_user.tenant_id, _plan_actual_id(current_user))


@router.post("/seleccionar", response_model=SuscripcionPagoOut)
def seleccionar_plan(payload: SeleccionarPlanIn, current_user: UserOut = Depends(get_current_user)):
    """Free plans apply instantly. Paid plans start a Wompi checkout instead —
    the plan is only assigned once the payment is confirmed (see /confirmar
    and the /webhooks/wompi handler)."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo verificar el plan")

    try:
        r = _fetch_plan_disponible(sconn, payload.plan_id, current_user.tenant_id)
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ese plan no está disponible")
        precio = float(r[4])
    finally:
        sconn.close()

    if precio <= 0:
        _aplicar_plan(current_user.tenant_id, payload.plan_id)
        return SuscripcionPagoOut(estado="pagado", plan=_plan_publico_out(r, actual=True))

    reference = f"{REFERENCE_PREFIX}{uuid.uuid4().hex[:24]}"
    amount_in_cents = round(precio * 100)

    conn = get_connection()
    try:
        conn.run(
            "INSERT INTO suscripcion_pagos (usuario_id, plan_id, monto, wompi_reference) "
            "VALUES (:uid, :pid, :monto, :ref)",
            uid=current_user.tenant_id, pid=payload.plan_id, monto=precio, ref=reference,
        )
    finally:
        conn.close()

    signature = wompi.integrity_signature(reference, amount_in_cents)
    checkout = WompiCheckoutOut(
        checkout_url=os.environ["WOMPI_CHECKOUT_URL"],
        public_key=os.environ["WOMPI_PUBLIC_KEY"],
        amount_in_cents=amount_in_cents,
        reference=reference,
        signature=signature,
        redirect_url=os.environ.get("WOMPI_SUBSCRIPTION_REDIRECT_URL") or os.environ["WOMPI_REDIRECT_URL"],
    )
    return SuscripcionPagoOut(estado="pendiente_pago", plan=_plan_publico_out(r, actual=False), wompi=checkout)


@router.post("/confirmar", response_model=SuscripcionPagoOut)
def confirmar_pago(payload: ConfirmarTransaccionIn, current_user: UserOut = Depends(get_current_user)):
    """Called by the frontend right after Wompi redirects back with
    ?id=<transaction_id>. The transaction's reference and status are read
    straight from Wompi (never trusted from the client)."""
    data = wompi.get_transaction(payload.transaction_id)
    if not data or not data.get("reference"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo consultar la transacción en Wompi")

    reference = data["reference"]
    if not reference.startswith(REFERENCE_PREFIX):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")

    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT plan_id, estado FROM suscripcion_pagos WHERE usuario_id = :uid AND wompi_reference = :ref",
            uid=current_user.tenant_id, ref=reference,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
        plan_id, estado_previo = rows[0]

        nuevo_estado = wompi.STATUS_MAP.get(data.get("status"), "pendiente_pago")
        if nuevo_estado != estado_previo:
            conn.run(
                "UPDATE suscripcion_pagos SET estado = :e, wompi_transaction_id = :tid, updated_at = now() "
                "WHERE usuario_id = :uid AND wompi_reference = :ref",
                e=nuevo_estado, tid=payload.transaction_id, uid=current_user.tenant_id, ref=reference,
            )
    finally:
        conn.close()

    if nuevo_estado == "pagado" and estado_previo != "pagado":
        _aplicar_plan(current_user.tenant_id, plan_id)

    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo verificar el plan")
    try:
        r = _fetch_plan_by_id(sconn, plan_id)
    finally:
        sconn.close()

    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")

    return SuscripcionPagoOut(estado=nuevo_estado, plan=_plan_publico_out(r, actual=(nuevo_estado == "pagado")))
