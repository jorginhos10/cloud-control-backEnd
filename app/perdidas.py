from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import PerdidaEstadisticasOut, PerdidaIn, PerdidaOut

router = APIRouter(prefix="/perdidas", dependencies=[Depends(get_current_user)])

PERDIDA_COLUMNS = [
    "id", "insumo_id", "insumo_nombre", "unidad_medida", "cantidad", "motivo", "descripcion",
    "costo_unitario", "valor_perdida", "stock_anterior", "stock_nuevo", "estado", "created_at",
]


def _row_to_perdida(row: dict) -> PerdidaOut:
    return PerdidaOut(
        id=row["id"], insumo_id=row["insumo_id"], insumo_nombre=row["insumo_nombre"],
        unidad_medida=row["unidad_medida"] or "", cantidad=float(row["cantidad"]), motivo=row["motivo"],
        descripcion=row["descripcion"] or "", costo_unitario=float(row["costo_unitario"]),
        valor_perdida=float(row["valor_perdida"]), stock_anterior=float(row["stock_anterior"]),
        stock_nuevo=float(row["stock_nuevo"]), estado=row["estado"], created_at=row["created_at"],
    )


def _get_perdida_or_404(conn, usuario_id: int, perdida_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(PERDIDA_COLUMNS)} FROM perdidas WHERE id = :id AND usuario_id = :uid",
        id=perdida_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pérdida no encontrada")
    return dict(zip(PERDIDA_COLUMNS, rows[0]))


@router.get("", response_model=list[PerdidaOut])
def list_perdidas(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    motivo: str = Query(default=""),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        hoy = date.today()
        desde = desde or hoy.replace(day=1)
        hasta = hasta or hoy

        clauses = ["usuario_id = :uid", "created_at::date BETWEEN :desde AND :hasta"]
        params: dict = {"uid": current_user.tenant_id, "desde": desde, "hasta": hasta}
        if motivo:
            clauses.append("motivo = :motivo")
            params["motivo"] = motivo

        rows = conn.run(
            f"SELECT {', '.join(PERDIDA_COLUMNS)} FROM perdidas WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC",
            **params,
        )
        return [_row_to_perdida(dict(zip(PERDIDA_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=PerdidaEstadisticasOut)
def estadisticas(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        hoy = date.today()
        desde = desde or hoy.replace(day=1)
        hasta = hasta or hoy

        row = conn.run(
            "SELECT COUNT(*), COALESCE(SUM(cantidad), 0), COALESCE(SUM(valor_perdida), 0) FROM perdidas "
            "WHERE usuario_id = :uid AND estado = 'aceptado' AND created_at::date BETWEEN :desde AND :hasta",
            uid=current_user.tenant_id, desde=desde, hasta=hasta,
        )[0]

        top = conn.run(
            "SELECT insumo_nombre, SUM(cantidad) AS total FROM perdidas "
            "WHERE usuario_id = :uid AND estado = 'aceptado' AND created_at::date BETWEEN :desde AND :hasta "
            "GROUP BY insumo_nombre ORDER BY total DESC LIMIT 1",
            uid=current_user.tenant_id, desde=desde, hasta=hasta,
        )

        return PerdidaEstadisticasOut(
            total_salidas=row[0],
            unidades_perdidas=float(row[1]),
            valor_perdida_total=float(row[2]),
            top_insumo_nombre=top[0][0] if top else None,
            top_insumo_cantidad=float(top[0][1]) if top else None,
        )
    finally:
        conn.close()


@router.post("", response_model=PerdidaOut, status_code=status.HTTP_201_CREATED)
def create_perdida(payload: PerdidaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        insumo = conn.run(
            "SELECT nombre, unidad_medida, cantidad_stock, precio_unitario FROM insumos "
            "WHERE id = :id AND usuario_id = :uid",
            id=payload.insumo_id, uid=current_user.tenant_id,
        )
        if not insumo:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El insumo indicado no existe")
        nombre, unidad, stock_actual, precio = insumo[0]
        stock_actual = float(stock_actual)
        precio = float(precio)

        stock_nuevo = max(0.0, stock_actual - payload.cantidad)
        valor_perdida = round(payload.cantidad * precio, 2)

        conn.run("UPDATE insumos SET cantidad_stock = :s WHERE id = :id", s=stock_nuevo, id=payload.insumo_id)

        rows = conn.run(
            "INSERT INTO perdidas (usuario_id, insumo_id, insumo_nombre, unidad_medida, cantidad, motivo, "
            "descripcion, costo_unitario, valor_perdida, stock_anterior, stock_nuevo) "
            "VALUES (:uid, :iid, :nombre, :unidad, :cant, :motivo, :descripcion, :costo, :valor, :sa, :sn) "
            f"RETURNING {', '.join(PERDIDA_COLUMNS)}",
            uid=current_user.tenant_id, iid=payload.insumo_id, nombre=nombre, unidad=unidad or "",
            cant=payload.cantidad, motivo=payload.motivo, descripcion=payload.descripcion.strip(),
            costo=precio, valor=valor_perdida, sa=stock_actual, sn=stock_nuevo,
        )
        return _row_to_perdida(dict(zip(PERDIDA_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.post("/{perdida_id}/anular", response_model=PerdidaOut)
def anular_perdida(perdida_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        perdida = _get_perdida_or_404(conn, current_user.tenant_id, perdida_id)
        if perdida["estado"] == "anulado":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta pérdida ya está anulada")

        conn.run(
            "UPDATE insumos SET cantidad_stock = cantidad_stock + :cant WHERE id = :id",
            cant=perdida["cantidad"], id=perdida["insumo_id"],
        )
        conn.run("UPDATE perdidas SET estado = 'anulado' WHERE id = :id", id=perdida_id)
        return _row_to_perdida(_get_perdida_or_404(conn, current_user.tenant_id, perdida_id))
    finally:
        conn.close()
