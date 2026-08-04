from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    CatalogoItemOut,
    CocinaItemOut,
    CocinaOrdenOut,
    SalonEstadisticasOut,
    SalonMesaOut,
    VentaCobrarIn,
    VentaCrearIn,
    VentaDirectaEstadisticasOut,
    VentaEstadoIn,
    VentaItemCantidadIn,
    VentaItemIn,
    VentaItemOut,
    VentaListadoItemOut,
    VentaListadoOut,
    VentaNotasIn,
    VentaOut,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

ACTIVOS = ("abierta", "en_preparacion", "lista")

SALON_COLUMNS = [
    "id", "numero", "nombre", "capacidad", "zona_key", "estado", "activo",
    "venta_id", "orden_estado", "orden_total", "items_count", "orden_inicio",
]

SALON_SELECT = """
    SELECT
        mesas.id, mesas.numero, mesas.nombre, mesas.capacidad, zonas.key AS zona_key,
        mesas.estado, mesas.activo,
        v.id AS venta_id, v.estado AS orden_estado, COALESCE(v.total, 0) AS orden_total,
        COALESCE(item_counts.items_count, 0) AS items_count, v.fecha_apertura AS orden_inicio
    FROM mesas
    JOIN zonas ON zonas.id = mesas.zona_id
    LEFT JOIN ventas v ON v.mesa_id = mesas.id AND v.estado IN ('abierta', 'en_preparacion', 'lista')
    LEFT JOIN (
        SELECT venta_id, COALESCE(SUM(cantidad), 0) AS items_count
        FROM venta_items
        GROUP BY venta_id
    ) item_counts ON item_counts.venta_id = v.id
    WHERE mesas.usuario_id = :uid
    ORDER BY mesas.numero
"""


def _row_to_salon_mesa(row: dict) -> SalonMesaOut:
    return SalonMesaOut(
        id=row["id"],
        numero=row["numero"],
        nombre=row["nombre"],
        capacidad=row["capacidad"],
        zona=row["zona_key"],
        estado=row["estado"],
        activo=row["activo"],
        venta_id=row["venta_id"],
        orden_estado=row["orden_estado"],
        orden_total=float(row["orden_total"]),
        items_count=row["items_count"],
        orden_inicio=row["orden_inicio"],
    )


@router.get("/salon", response_model=list[SalonMesaOut])
def salon(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(SALON_SELECT, uid=current_user.tenant_id)
        return [_row_to_salon_mesa(dict(zip(SALON_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/salon/estadisticas", response_model=SalonEstadisticasOut)
def salon_estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE estado = 'disponible'), "
            "COUNT(*) FILTER (WHERE estado = 'ocupada'), "
            "COUNT(*) FILTER (WHERE estado = 'reservada') "
            "FROM mesas WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        ingresos = conn.run(
            "SELECT COALESCE(SUM(total), 0) FROM ventas "
            "WHERE usuario_id = :uid AND estado IN ('abierta', 'en_preparacion', 'lista')",
            uid=current_user.tenant_id,
        )[0][0]
        return SalonEstadisticasOut(
            total=row[0], disponibles=row[1], ocupadas=row[2], reservadas=row[3], ingresos_en_curso=float(ingresos)
        )
    finally:
        conn.close()


@router.get("/ventas/estadisticas-directa", response_model=VentaDirectaEstadisticasOut)
def ventas_directa_estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas "
            "WHERE usuario_id = :uid AND tipo = 'directa' AND estado = 'cerrada' AND fecha_cierre::date = :hoy",
            uid=current_user.tenant_id, hoy=date.today(),
        )[0]
        return VentaDirectaEstadisticasOut(ventas_hoy=row[0], ingresos_hoy=float(row[1]))
    finally:
        conn.close()


CATALOGO_SELECT = """
    SELECT
        recetas.id, recetas.nombre, receta_categorias.label AS categoria, recetas.precio_venta,
        (
            SELECT MIN(FLOOR(i.cantidad_stock / ri.cantidad))
            FROM receta_insumos ri
            JOIN insumos i ON i.id = ri.id_insumo
            WHERE ri.id_receta = recetas.id
        ) AS disponible
    FROM recetas
    JOIN receta_categorias ON receta_categorias.id = recetas.categoria_id
    WHERE recetas.usuario_id = :uid AND recetas.activo = true
"""


@router.get("/ventas/catalogo", response_model=list[CatalogoItemOut])
def catalogo(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                CATALOGO_SELECT + " AND recetas.nombre ILIKE :q ORDER BY recetas.nombre",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(CATALOGO_SELECT + " ORDER BY recetas.nombre", uid=current_user.tenant_id)
        return [
            CatalogoItemOut(
                id=r[0], nombre=r[1], categoria=r[2], precio_venta=float(r[3]),
                disponible=int(r[4]) if r[4] is not None else None,
            )
            for r in rows
        ]
    finally:
        conn.close()


COCINA_ORDENES_SELECT = """
    SELECT ventas.id, ventas.tipo, ventas.estado, ventas.notas, ventas.fecha_apertura,
           mesas.numero AS mesa_numero, mesas.nombre AS mesa_nombre, zonas.key AS mesa_zona
    FROM ventas
    LEFT JOIN mesas ON mesas.id = ventas.mesa_id
    LEFT JOIN zonas ON zonas.id = mesas.zona_id
    WHERE ventas.usuario_id = :uid AND ventas.estado IN ('abierta', 'en_preparacion', 'lista')
    ORDER BY ventas.fecha_apertura ASC
"""

COCINA_ITEMS_SELECT = """
    SELECT vi.id, vi.nombre, vi.cantidad, COALESCE(rc.label, 'Otro') AS categoria
    FROM venta_items vi
    LEFT JOIN recetas r ON r.id = vi.receta_id
    LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id
    WHERE vi.venta_id = :id
    ORDER BY categoria, vi.nombre
"""


@router.get("/cocina/ordenes", response_model=list[CocinaOrdenOut])
def cocina_ordenes(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(COCINA_ORDENES_SELECT, uid=current_user.tenant_id)
        ordenes = []
        for r in rows:
            item_rows = conn.run(COCINA_ITEMS_SELECT, id=r[0])
            ordenes.append(
                CocinaOrdenOut(
                    id=r[0], tipo=r[1], estado=r[2], notas=r[3], fecha_apertura=r[4],
                    mesa_numero=r[5], mesa_nombre=r[6], mesa_zona=r[7],
                    items=[CocinaItemOut(id=i[0], nombre=i[1], cantidad=i[2], categoria=i[3]) for i in item_rows],
                )
            )
        return ordenes
    finally:
        conn.close()


VENTA_COLUMNS = [
    "id", "mesa_id", "tipo", "estado", "total", "notas", "metodo_pago",
    "pago_efectivo", "pago_tarjeta", "pago_transferencia", "propina",
    "fecha_apertura", "fecha_cierre",
]
ITEM_COLUMNS = ["id", "receta_id", "nombre", "cantidad", "precio_unitario", "subtotal"]


def _row_to_item(row) -> VentaItemOut:
    d = dict(zip(ITEM_COLUMNS, row))
    return VentaItemOut(
        id=d["id"], receta_id=d["receta_id"], nombre=d["nombre"], cantidad=d["cantidad"],
        precio_unitario=float(d["precio_unitario"]), subtotal=float(d["subtotal"]),
    )


def _get_venta_con_items(conn, usuario_id: int, venta_id: int) -> VentaOut:
    rows = conn.run(
        f"SELECT {', '.join(VENTA_COLUMNS)} FROM ventas WHERE id = :id AND usuario_id = :uid",
        id=venta_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")
    v = dict(zip(VENTA_COLUMNS, rows[0]))
    item_rows = conn.run(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM venta_items WHERE venta_id = :id ORDER BY creado_en",
        id=venta_id,
    )
    return VentaOut(
        id=v["id"],
        mesa_id=v["mesa_id"],
        tipo=v["tipo"],
        estado=v["estado"],
        total=float(v["total"]),
        notas=v["notas"],
        metodo_pago=v["metodo_pago"],
        pago_efectivo=float(v["pago_efectivo"]),
        pago_tarjeta=float(v["pago_tarjeta"]),
        pago_transferencia=float(v["pago_transferencia"]),
        propina=float(v["propina"]),
        fecha_apertura=v["fecha_apertura"],
        fecha_cierre=v["fecha_cierre"],
        items=[_row_to_item(r) for r in item_rows],
    )


def _recalcular_total(conn, venta_id: int) -> None:
    conn.run(
        "UPDATE ventas SET total = (SELECT COALESCE(SUM(subtotal), 0) FROM venta_items WHERE venta_id = :id) "
        "WHERE id = :id",
        id=venta_id,
    )


def _liberar_mesa_si_corresponde(conn, mesa_id: int | None) -> None:
    if mesa_id is None:
        return
    activas = conn.run(
        "SELECT 1 FROM ventas WHERE mesa_id = :mid AND estado IN ('abierta', 'en_preparacion', 'lista')",
        mid=mesa_id,
    )
    if not activas:
        conn.run(
            "UPDATE mesas SET estado = 'disponible' WHERE id = :id AND estado = 'ocupada'",
            id=mesa_id,
        )


POR_PAGINA = 25


@router.get("/ventas/listado", response_model=VentaListadoOut)
def listado_ventas(
    buscar: str = Query(default=""),
    estado: str = Query(default=""),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        hoy = date.today()
        desde = desde or hoy
        hasta = hasta or hoy

        clauses = ["v.usuario_id = :uid", "v.fecha_apertura::date BETWEEN :desde AND :hasta"]
        params: dict = {"uid": current_user.tenant_id, "desde": desde, "hasta": hasta}
        if estado:
            clauses.append("v.estado = :estado")
            params["estado"] = estado
        if buscar.strip():
            clauses.append("(CAST(v.id AS TEXT) ILIKE :buscar OR CAST(m.numero AS TEXT) ILIKE :buscar)")
            params["buscar"] = f"%{buscar.strip()}%"
        where_sql = " AND ".join(clauses)

        totales = conn.run(
            f"SELECT COUNT(DISTINCT v.id), COALESCE(SUM(v.total), 0) FROM ventas v "
            f"LEFT JOIN mesas m ON m.id = v.mesa_id WHERE {where_sql}",
            **params,
        )[0]
        total, monto_total = totales[0], float(totales[1])
        total_paginas = max(1, -(-total // POR_PAGINA))

        offset = (pagina - 1) * POR_PAGINA
        rows = conn.run(
            f"SELECT v.id, v.fecha_apertura, v.tipo, v.estado, m.numero AS mesa_numero, "
            f"COALESCE(ic.cnt, 0) AS platos, v.total, v.metodo_pago "
            f"FROM ventas v "
            f"LEFT JOIN mesas m ON m.id = v.mesa_id "
            f"LEFT JOIN (SELECT venta_id, COALESCE(SUM(cantidad), 0) AS cnt FROM venta_items GROUP BY venta_id) ic "
            f"ON ic.venta_id = v.id "
            f"WHERE {where_sql} "
            f"ORDER BY v.fecha_apertura DESC LIMIT :limit OFFSET :offset",
            limit=POR_PAGINA, offset=offset, **params,
        )
        items = [
            VentaListadoItemOut(
                id=r[0], fecha=r[1], tipo=r[2], estado=r[3], mesa_numero=r[4],
                platos=r[5], total=float(r[6]), metodo_pago=r[7],
            )
            for r in rows
        ]

        return VentaListadoOut(
            items=items, total=total, monto_total=monto_total, pagina=pagina, total_paginas=total_paginas
        )
    finally:
        conn.close()


@router.get("/ventas/{venta_id}", response_model=VentaOut)
def get_venta(venta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.get("/ventas/mesa/{mesa_id}", response_model=list[VentaOut])
def ventas_por_mesa(mesa_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT id FROM ventas WHERE mesa_id = :mid AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista') ORDER BY fecha_apertura",
            mid=mesa_id, uid=current_user.tenant_id,
        )
        return [_get_venta_con_items(conn, current_user.tenant_id, r[0]) for r in rows]
    finally:
        conn.close()


@router.post("/ventas", response_model=VentaOut, status_code=status.HTTP_201_CREATED)
def abrir_orden(payload: VentaCrearIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        if payload.mesa_id is None:
            rows = conn.run(
                "INSERT INTO ventas (mesa_id, tipo, estado, usuario_id) VALUES (NULL, 'directa', 'abierta', :uid) "
                f"RETURNING {', '.join(VENTA_COLUMNS)}",
                uid=current_user.tenant_id,
            )
            return _get_venta_con_items(conn, current_user.tenant_id, rows[0][0])

        mesa = conn.run(
            "SELECT id FROM mesas WHERE id = :id AND usuario_id = :uid", id=payload.mesa_id, uid=current_user.tenant_id
        )
        if not mesa:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")

        existente = conn.run(
            "SELECT id FROM ventas WHERE mesa_id = :mid AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista') ORDER BY fecha_apertura LIMIT 1",
            mid=payload.mesa_id, uid=current_user.tenant_id,
        )
        if existente:
            return _get_venta_con_items(conn, current_user.tenant_id, existente[0][0])

        rows = conn.run(
            "INSERT INTO ventas (mesa_id, tipo, estado, usuario_id) VALUES (:mesa_id, 'mesa', 'abierta', :uid) "
            f"RETURNING {', '.join(VENTA_COLUMNS)}",
            mesa_id=payload.mesa_id,
            uid=current_user.tenant_id,
        )
        conn.run("UPDATE mesas SET estado = 'ocupada' WHERE id = :id", id=payload.mesa_id)
        venta_id = rows[0][0]
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


def _get_venta_or_404(conn, usuario_id: int, venta_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(VENTA_COLUMNS)} FROM ventas WHERE id = :id AND usuario_id = :uid",
        id=venta_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")
    return dict(zip(VENTA_COLUMNS, rows[0]))


@router.post("/ventas/{venta_id}/items", response_model=VentaOut, status_code=status.HTTP_201_CREATED)
def agregar_item(venta_id: int, payload: VentaItemIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        receta = conn.run(
            "SELECT nombre, precio_venta FROM recetas WHERE id = :id AND usuario_id = :uid AND activo = true",
            id=payload.receta_id, uid=current_user.tenant_id,
        )
        if not receta:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La receta indicada no existe o está inactiva")
        nombre, precio_venta = receta[0][0], float(receta[0][1])

        disponible = conn.run(
            "SELECT MIN(FLOOR(i.cantidad_stock / ri.cantidad)) FROM receta_insumos ri "
            "JOIN insumos i ON i.id = ri.id_insumo WHERE ri.id_receta = :id",
            id=payload.receta_id,
        )[0][0]
        if disponible is not None:
            ya_en_carrito = conn.run(
                "SELECT COALESCE(SUM(cantidad), 0) FROM venta_items WHERE venta_id = :vid AND receta_id = :rid",
                vid=venta_id,
                rid=payload.receta_id,
            )[0][0]
            restante = int(disponible) - int(ya_en_carrito)
            if payload.cantidad > restante:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Stock insuficiente para \"{nombre}\": disponible {max(restante, 0)}",
                )

        existente = conn.run(
            "SELECT id, cantidad FROM venta_items WHERE venta_id = :vid AND receta_id = :rid",
            vid=venta_id,
            rid=payload.receta_id,
        )
        if existente:
            item_id, cantidad_actual = existente[0]
            nueva_cantidad = cantidad_actual + payload.cantidad
            conn.run(
                "UPDATE venta_items SET cantidad = :cant, subtotal = :subtotal WHERE id = :id",
                cant=nueva_cantidad,
                subtotal=round(nueva_cantidad * precio_venta, 2),
                id=item_id,
            )
        else:
            subtotal = round(payload.cantidad * precio_venta, 2)
            conn.run(
                "INSERT INTO venta_items (venta_id, receta_id, nombre, cantidad, precio_unitario, subtotal) "
                "VALUES (:vid, :rid, :nombre, :cant, :precio, :subtotal)",
                vid=venta_id,
                rid=payload.receta_id,
                nombre=nombre,
                cant=payload.cantidad,
                precio=precio_venta,
                subtotal=subtotal,
            )
        _recalcular_total(conn, venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.patch("/ventas/{venta_id}/items/{item_id}", response_model=VentaOut)
def actualizar_cantidad_item(
    venta_id: int, item_id: int, payload: VentaItemCantidadIn, current_user: UserOut = Depends(get_current_user)
):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        item = conn.run(
            "SELECT receta_id, precio_unitario FROM venta_items WHERE id = :iid AND venta_id = :vid",
            iid=item_id,
            vid=venta_id,
        )
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
        receta_id, precio_unitario = item[0]

        if receta_id is not None:
            disponible = conn.run(
                "SELECT MIN(FLOOR(i.cantidad_stock / ri.cantidad)) FROM receta_insumos ri "
                "JOIN insumos i ON i.id = ri.id_insumo WHERE ri.id_receta = :id",
                id=receta_id,
            )[0][0]
            if disponible is not None:
                otros_en_carrito = conn.run(
                    "SELECT COALESCE(SUM(cantidad), 0) FROM venta_items "
                    "WHERE venta_id = :vid AND receta_id = :rid AND id != :iid",
                    vid=venta_id,
                    rid=receta_id,
                    iid=item_id,
                )[0][0]
                restante = int(disponible) - int(otros_en_carrito)
                if payload.cantidad > restante:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Stock insuficiente: disponible {max(restante, 0)}",
                    )

        conn.run(
            "UPDATE venta_items SET cantidad = :cant, subtotal = :subtotal WHERE id = :id",
            cant=payload.cantidad,
            subtotal=round(payload.cantidad * float(precio_unitario), 2),
            id=item_id,
        )
        _recalcular_total(conn, venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.delete("/ventas/{venta_id}/items/{item_id}", response_model=VentaOut)
def eliminar_item(venta_id: int, item_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        deleted = conn.run(
            "DELETE FROM venta_items WHERE id = :iid AND venta_id = :vid RETURNING id",
            iid=item_id,
            vid=venta_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
        _recalcular_total(conn, venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.patch("/ventas/{venta_id}/notas", response_model=VentaOut)
def actualizar_notas(venta_id: int, payload: VentaNotasIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")
        conn.run("UPDATE ventas SET notas = :n WHERE id = :id", n=payload.notas.strip(), id=venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.patch("/ventas/{venta_id}/estado", response_model=VentaOut)
def cambiar_estado_cocina(venta_id: int, payload: VentaEstadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS or payload.estado not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transición de estado inválida")
        conn.run("UPDATE ventas SET estado = :e WHERE id = :id", e=payload.estado, id=venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.post("/ventas/{venta_id}/cobrar", response_model=VentaOut)
def cobrar_orden(venta_id: int, payload: VentaCobrarIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        items = conn.run(
            "SELECT receta_id, cantidad FROM venta_items WHERE venta_id = :id AND receta_id IS NOT NULL",
            id=venta_id,
        )
        if not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La orden no tiene ítems para cobrar")

        consumo: dict[int, float] = {}
        for receta_id, cantidad in items:
            ingredientes = conn.run(
                "SELECT id_insumo, cantidad FROM receta_insumos WHERE id_receta = :id", id=receta_id
            )
            for id_insumo, cantidad_receta in ingredientes:
                consumo[id_insumo] = consumo.get(id_insumo, 0) + float(cantidad_receta) * cantidad

        for id_insumo, requerido in consumo.items():
            stock = conn.run("SELECT nombre, cantidad_stock FROM insumos WHERE id = :id", id=id_insumo)[0]
            if float(stock[1]) < requerido:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Stock insuficiente de \"{stock[0]}\" para completar el cobro",
                )

        for id_insumo, requerido in consumo.items():
            conn.run(
                "UPDATE insumos SET cantidad_stock = cantidad_stock - :cant WHERE id = :id",
                cant=requerido,
                id=id_insumo,
            )

        conn.run(
            "UPDATE ventas SET estado = 'cerrada', fecha_cierre = now(), metodo_pago = :mp, "
            "pago_efectivo = :pe, pago_tarjeta = :pt, pago_transferencia = :ptr, propina = :prop "
            "WHERE id = :id",
            mp=payload.metodo_pago,
            pe=payload.pago_efectivo,
            pt=payload.pago_tarjeta,
            ptr=payload.pago_transferencia,
            prop=payload.propina,
            id=venta_id,
        )
        _liberar_mesa_si_corresponde(conn, venta["mesa_id"])
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.delete("/ventas/{venta_id}", response_model=VentaOut)
def cancelar_orden(venta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")
        conn.run("UPDATE ventas SET estado = 'cancelada', fecha_cierre = now() WHERE id = :id", id=venta_id)
        _liberar_mesa_si_corresponde(conn, venta["mesa_id"])
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()
