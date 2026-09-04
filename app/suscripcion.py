from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user
from app.database import get_connection, get_superadmin_connection
from app.schemas import PlanPublicoOut, SeleccionarPlanIn

router = APIRouter(prefix="/suscripcion", dependencies=[Depends(get_current_user)])


def _plan_actual_id(current_user: UserOut) -> int | None:
    conn = get_connection()
    try:
        rows = conn.run("SELECT plan_id FROM usuarios WHERE id = :id", id=current_user.tenant_id)
        return rows[0][0] if rows else None
    finally:
        conn.close()


@router.get("/planes", response_model=list[PlanPublicoOut])
def planes(current_user: UserOut = Depends(get_current_user)):
    """Plans curated by the SuperAdmin, read-only from here — public active
    plans, plus any private plan explicitly assigned to this restaurant."""
    plan_actual = _plan_actual_id(current_user)

    try:
        sconn = get_superadmin_connection()
    except Exception:
        return []

    try:
        rows = sconn.run(
            """
            SELECT p.id, p.nombre, p.slug, p.descripcion, p.precio, p.periodo, p.color, p.caracteristicas, p.destacado
            FROM planes p
            WHERE p.activo = true
              AND (p.visibilidad = 'publico'
                   OR EXISTS (SELECT 1 FROM plan_comercios pc WHERE pc.plan_id = p.id AND pc.comercio_id = :tid))
            ORDER BY p.orden ASC, p.id ASC
            """,
            tid=current_user.tenant_id,
        )
        return [
            PlanPublicoOut(
                id=r[0], nombre=r[1], slug=r[2], descripcion=r[3], precio=float(r[4]),
                periodo=r[5], color=r[6], caracteristicas=r[7], destacado=r[8],
                actual=(r[0] == plan_actual),
            )
            for r in rows
        ]
    finally:
        sconn.close()


@router.post("/seleccionar", response_model=PlanPublicoOut)
def seleccionar_plan(payload: SeleccionarPlanIn, current_user: UserOut = Depends(get_current_user)):
    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo verificar el plan")

    try:
        rows = sconn.run(
            """
            SELECT p.id, p.nombre, p.slug, p.descripcion, p.precio, p.periodo, p.color, p.caracteristicas, p.destacado
            FROM planes p
            WHERE p.id = :id AND p.activo = true
              AND (p.visibilidad = 'publico'
                   OR EXISTS (SELECT 1 FROM plan_comercios pc WHERE pc.plan_id = p.id AND pc.comercio_id = :tid))
            """,
            id=payload.plan_id, tid=current_user.tenant_id,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ese plan no está disponible")
        r = rows[0]
    finally:
        sconn.close()

    conn = get_connection()
    try:
        conn.run(
            "UPDATE usuarios SET plan_id = :pid, plan_actualizado_en = now() WHERE id = :id",
            pid=payload.plan_id, id=current_user.tenant_id,
        )
    finally:
        conn.close()

    return PlanPublicoOut(
        id=r[0], nombre=r[1], slug=r[2], descripcion=r[3], precio=float(r[4]),
        periodo=r[5], color=r[6], caracteristicas=r[7], destacado=r[8], actual=True,
    )
