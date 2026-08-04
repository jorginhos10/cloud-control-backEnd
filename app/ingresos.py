from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import IngresoEstadisticasOut, IngresoIn, IngresoItemOut, IngresoOut

router = APIRouter(prefix="/ingresos", dependencies=[Depends(get_current_user)])

INGRESO_COLUMNS = [
    "id", "radicado", "fecha", "concepto", "impuesto_porcentaje",
    "subtotal", "impuesto", "total", "estado", "created_at",
]
ITEM_COLUMNS = ["id", "insumo_id", "articulo", "cantidad", "precio_unitario", "subtotal"]


def _generar_radicado(conn, usuario_id: int) -> str:
    hoy = date.today().strftime("%Y%m%d")
    count = conn.run(
        "SELECT COUNT(*) FROM ingresos WHERE usuario_id = :uid AND radicado LIKE :prefijo",
        uid=usuario_id, prefijo=f"{hoy}-%",
    )[0][0]
    return f"{hoy}-{count + 1:04d}"


def _get_items(conn, ingreso_id: int) -> list[IngresoItemOut]:
    rows = conn.run(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM ingreso_items WHERE ingreso_id = :id ORDER BY id",
        id=ingreso_id,
    )
    return [
        IngresoItemOut(
            id=r[0], insumo_id=r[1], articulo=r[2],
            cantidad=float(r[3]), precio_unitario=float(r[4]), subtotal=float(r[5]),
        )
        for r in rows
    ]


def _row_to_ingreso(conn, row: dict) -> IngresoOut:
    return IngresoOut(
        id=row["id"], radicado=row["radicado"], fecha=row["fecha"], concepto=row["concepto"],
        impuesto_porcentaje=float(row["impuesto_porcentaje"]), subtotal=float(row["subtotal"]),
        impuesto=float(row["impuesto"]), total=float(row["total"]), estado=row["estado"],
        created_at=row["created_at"], items=_get_items(conn, row["id"]),
    )


def _get_ingreso_or_404(conn, usuario_id: int, ingreso_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(INGRESO_COLUMNS)} FROM ingresos WHERE id = :id AND usuario_id = :uid",
        id=ingreso_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingreso no encontrado")
    return dict(zip(INGRESO_COLUMNS, rows[0]))


def _aplicar_stock(conn, items, signo: int) -> None:
    """signo=+1 al crear/reactivar (entrada), signo=-1 al anular/editar/eliminar (reversa)."""
    for item in items:
        insumo_id = item["insumo_id"] if isinstance(item, dict) else item.insumo_id
        cantidad = item["cantidad"] if isinstance(item, dict) else item.cantidad
        if insumo_id is None:
            continue
        conn.run(
            "UPDATE insumos SET cantidad_stock = GREATEST(0, cantidad_stock + :delta) WHERE id = :id",
            delta=signo * cantidad,
            id=insumo_id,
        )


def _insertar_items(conn, usuario_id: int, ingreso_id: int, items) -> None:
    for item in items:
        insumo_id = item.insumo_id
        if insumo_id is not None:
            existe = conn.run(
                "SELECT 1 FROM insumos WHERE id = :id AND usuario_id = :uid", id=insumo_id, uid=usuario_id
            )
            if not existe:
                insumo_id = None
        conn.run(
            "INSERT INTO ingreso_items (ingreso_id, insumo_id, articulo, cantidad, precio_unitario, subtotal) "
            "VALUES (:iid, :insumo, :articulo, :cant, :precio, :subtotal)",
            iid=ingreso_id, insumo=insumo_id, articulo=item.articulo.strip(),
            cant=item.cantidad, precio=item.precio_unitario,
            subtotal=round(item.cantidad * item.precio_unitario, 2),
        )


def _calcular_totales(items) -> tuple[float, float]:
    subtotal = round(sum(i.cantidad * i.precio_unitario for i in items), 2)
    return subtotal, subtotal


@router.get("", response_model=list[IngresoOut])
def list_ingresos(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    estado: str = Query(default=""),
    q: str = Query(default=""),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        hoy = date.today()
        desde = desde or hoy.replace(day=1)
        hasta = hasta or hoy

        clauses = ["usuario_id = :uid", "fecha BETWEEN :desde AND :hasta"]
        params = {"uid": current_user.tenant_id, "desde": desde, "hasta": hasta}
        if estado:
            clauses.append("estado = :estado")
            params["estado"] = estado
        if q.strip():
            clauses.append("concepto ILIKE :q")
            params["q"] = f"%{q.strip()}%"

        rows = conn.run(
            f"SELECT {', '.join(INGRESO_COLUMNS)} FROM ingresos WHERE {' AND '.join(clauses)} "
            "ORDER BY fecha DESC, id DESC",
            **params,
        )
        return [_row_to_ingreso(conn, dict(zip(INGRESO_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=IngresoEstadisticasOut)
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
            "SELECT COUNT(*) FILTER (WHERE estado != 'anulado'), "
            "COALESCE(SUM(total) FILTER (WHERE estado != 'anulado'), 0), "
            "COUNT(*) FILTER (WHERE estado = 'anulado') "
            "FROM ingresos WHERE usuario_id = :uid AND fecha BETWEEN :desde AND :hasta",
            uid=current_user.tenant_id, desde=desde, hasta=hasta,
        )[0]
        return IngresoEstadisticasOut(ingresos_periodo=row[0], total_ingresado=float(row[1]), anulados=row[2])
    finally:
        conn.close()


@router.get("/{ingreso_id}", response_model=IngresoOut)
def get_ingreso(ingreso_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_ingreso(conn, _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id))
    finally:
        conn.close()


def _crear_ingreso(conn, usuario_id: int, concepto: str, impuesto_porcentaje: float, items) -> int:
    subtotal, _ = _calcular_totales(items)
    impuesto = round(subtotal * impuesto_porcentaje / 100, 2)
    total = round(subtotal + impuesto, 2)
    radicado = _generar_radicado(conn, usuario_id)

    rows = conn.run(
        "INSERT INTO ingresos (usuario_id, radicado, concepto, impuesto_porcentaje, subtotal, impuesto, total, estado) "
        "VALUES (:uid, :radicado, :concepto, :pct, :subtotal, :impuesto, :total, 'aceptado') RETURNING id",
        uid=usuario_id, radicado=radicado, concepto=concepto.strip(),
        pct=impuesto_porcentaje, subtotal=subtotal, impuesto=impuesto, total=total,
    )
    ingreso_id = rows[0][0]

    _insertar_items(conn, usuario_id, ingreso_id, items)
    _aplicar_stock(conn, items, signo=1)
    return ingreso_id


@router.post("", response_model=IngresoOut, status_code=status.HTTP_201_CREATED)
def create_ingreso(payload: IngresoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        ingreso_id = _crear_ingreso(
            conn, current_user.tenant_id, payload.concepto, payload.impuesto_porcentaje, payload.items
        )
        return _row_to_ingreso(conn, _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id))
    finally:
        conn.close()


@router.put("/{ingreso_id}", response_model=IngresoOut)
def update_ingreso(ingreso_id: int, payload: IngresoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        ingreso = _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id)
        if ingreso["estado"] == "anulado":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes editar un ingreso anulado")

        items_previos = _get_items(conn, ingreso_id)
        _aplicar_stock(conn, items_previos, signo=-1)
        conn.run("DELETE FROM ingreso_items WHERE ingreso_id = :id", id=ingreso_id)

        subtotal, _ = _calcular_totales(payload.items)
        impuesto = round(subtotal * payload.impuesto_porcentaje / 100, 2)
        total = round(subtotal + impuesto, 2)

        conn.run(
            "UPDATE ingresos SET concepto = :concepto, impuesto_porcentaje = :pct, subtotal = :subtotal, "
            "impuesto = :impuesto, total = :total WHERE id = :id AND usuario_id = :uid",
            id=ingreso_id, uid=current_user.tenant_id, concepto=payload.concepto.strip(), pct=payload.impuesto_porcentaje,
            subtotal=subtotal, impuesto=impuesto, total=total,
        )

        _insertar_items(conn, current_user.tenant_id, ingreso_id, payload.items)
        _aplicar_stock(conn, payload.items, signo=1)
        return _row_to_ingreso(conn, _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id))
    finally:
        conn.close()


@router.post("/{ingreso_id}/anular", response_model=IngresoOut)
def anular_ingreso(ingreso_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        ingreso = _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id)
        if ingreso["estado"] == "anulado":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este ingreso ya está anulado")

        items = _get_items(conn, ingreso_id)
        _aplicar_stock(conn, items, signo=-1)
        conn.run("UPDATE ingresos SET estado = 'anulado' WHERE id = :id", id=ingreso_id)
        return _row_to_ingreso(conn, _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id))
    finally:
        conn.close()


@router.delete("/{ingreso_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingreso(ingreso_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        ingreso = _get_ingreso_or_404(conn, current_user.tenant_id, ingreso_id)
        if ingreso["estado"] != "anulado":
            items = _get_items(conn, ingreso_id)
            _aplicar_stock(conn, items, signo=-1)
        conn.run("DELETE FROM ingresos WHERE id = :id AND usuario_id = :uid", id=ingreso_id, uid=current_user.tenant_id)
    finally:
        conn.close()
