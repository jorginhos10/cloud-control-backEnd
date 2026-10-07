from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.numeracion_ordenes import generar_numero_orden
from app.sabores import sabores_por_receta
from app.toppings import toppings_por_receta
from app.schemas import (
    CatalogoItemOut,
    CocinaItemOut,
    CocinaOrdenOut,
    DashboardProductoCantidadOut,
    PropinaItemOut,
    SalonEstadisticasOut,
    SalonMesaOut,
    MesaCambioIn,
    VentaClienteIn,
    VentaCobrarIn,
    VentaCrearIn,
    VentaCuponIn,
    VentaDirectaEstadisticasOut,
    VentaEstadoIn,
    VentaItemCantidadIn,
    VentaItemIn,
    VentaItemOut,
    VentaListadoItemOut,
    VentaListadoOut,
    VentaNotasIn,
    VentaOut,
    VentaPagoIn,
    VentaPagoOut,
    VentaCuentaDivididaOut,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

ACTIVOS = ("abierta", "en_preparacion", "lista", "entregada")

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
    LEFT JOIN ventas v ON v.mesa_id = mesas.id AND v.estado IN ('abierta', 'en_preparacion', 'lista', 'entregada')
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
            "WHERE usuario_id = :uid AND estado IN ('abierta', 'en_preparacion', 'lista', 'entregada')",
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


@router.get("/ventas/mis-ventas-hoy", response_model=VentaDirectaEstadisticasOut)
def mis_ventas_hoy(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas "
            "WHERE usuario_id = :uid AND creado_por_id = :cid AND estado = 'cerrada' AND fecha_cierre::date = :hoy",
            uid=current_user.tenant_id, cid=current_user.id, hoy=date.today(),
        )[0]
        return VentaDirectaEstadisticasOut(ventas_hoy=row[0], ingresos_hoy=float(row[1]))
    finally:
        conn.close()


@router.get("/ventas/mis-propinas", response_model=list[PropinaItemOut])
def mis_propinas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT v.id, v.fecha_cierre, v.tipo, m.numero AS mesa_numero, v.propina, v.total, v.metodo_pago "
            "FROM ventas v "
            "LEFT JOIN mesas m ON m.id = v.mesa_id "
            "WHERE v.usuario_id = :uid AND v.creado_por_id = :cid "
            "AND v.estado = 'cerrada' AND v.propina > 0 AND v.fecha_cierre::date = :hoy "
            "ORDER BY v.fecha_cierre DESC",
            uid=current_user.tenant_id, cid=current_user.id, hoy=date.today(),
        )
        return [
            PropinaItemOut(
                id=r[0], fecha=r[1], tipo=r[2], mesa_numero=r[3],
                propina=float(r[4]), total=float(r[5]), metodo_pago=r[6],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/ventas/mis-ventas-hoy/productos", response_model=list[DashboardProductoCantidadOut])
def mis_productos_hoy(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT vi.nombre, SUM(vi.cantidad) AS cantidad "
            "FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id "
            "WHERE v.usuario_id = :uid AND v.creado_por_id = :cid "
            "AND v.estado = 'cerrada' AND v.fecha_cierre::date = :hoy "
            "GROUP BY vi.nombre ORDER BY cantidad DESC LIMIT 5",
            uid=current_user.tenant_id, cid=current_user.id, hoy=date.today(),
        )
        return [DashboardProductoCantidadOut(producto=r[0], cantidad=r[1]) for r in rows]
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
        ) AS disponible,
        recetas.imagen_url
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
        sabores = sabores_por_receta(conn, [r[0] for r in rows])
        toppings = toppings_por_receta(conn, [r[0] for r in rows])
        return [
            CatalogoItemOut(
                id=r[0], nombre=r[1], categoria=r[2], precio_venta=float(r[3]),
                disponible=int(r[4]) if r[4] is not None else None,
                imagen_url=r[5],
                sabores=sabores.get(r[0], []),
                toppings=toppings.get(r[0], []),
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
    WHERE ventas.usuario_id = :uid AND (
        ventas.estado IN ('abierta', 'en_preparacion', 'lista')
        -- Las canceladas hace poco se envían también para que la cocina avise que se canceló la preparación.
        OR (ventas.estado = 'cancelada' AND ventas.fecha_cierre > now() - interval '3 minutes')
    )
    ORDER BY ventas.fecha_apertura ASC
"""

COCINA_ITEMS_SELECT = """
    SELECT vi.id, vi.nombre, vi.cantidad, COALESCE(rc.label, 'Otro') AS categoria, vi.sabor_nombre, vi.topping_nombre,
           r.categoria_id
    FROM venta_items vi
    LEFT JOIN recetas r ON r.id = vi.receta_id
    LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id
    WHERE vi.venta_id = :id
    ORDER BY categoria, vi.nombre
"""

# Los domicilios ya aprobados (estado "preparacion") o listos entran a la misma pantalla de
# cocina que las ventas; los "pendiente" siguen esperando la aprobación del negocio en Domicilios.
DOMICILIO_ORDENES_SELECT = """
    SELECT id, tipo, estado, notas, created_at, nombre_cliente, direccion
    FROM domicilios
    WHERE usuario_id = :uid AND (
        estado IN ('preparacion', 'listo')
        OR (estado = 'cancelado' AND updated_at > now() - interval '3 minutes')
    )
    ORDER BY created_at ASC
"""

DOMICILIO_ITEMS_SELECT = """
    SELECT di.id, di.nombre, di.cantidad, COALESCE(rc.label, 'Otro') AS categoria, di.sabor_nombre, di.topping_nombre,
           r.categoria_id
    FROM domicilio_items di
    LEFT JOIN recetas r ON r.id = di.receta_id
    LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id
    WHERE di.domicilio_id = :id
    ORDER BY categoria, di.nombre
"""

# El estado de un domicilio no comparte enum con el de una venta; se traduce al que ya
# entienden las columnas de cocina (pendiente no aplica: nunca llega a esta pantalla).
_ESTADO_DOMICILIO_A_COCINA = {"preparacion": "en_preparacion", "listo": "lista", "cancelado": "cancelada"}


def _filtrar_items_por_categoria(item_rows, categoria_ids: set[int] | None) -> list[CocinaItemOut]:
    """Si el cocinero tiene categorías asignadas, deja afuera los ítems de otras categorías —
    un ítem sin receta (categoria_id NULL, p. ej. un cargo suelto) nunca le aparece a nadie con
    categorías asignadas, ya que no hay forma de saber a quién le toca."""
    items = item_rows if categoria_ids is None else [i for i in item_rows if i[6] in categoria_ids]
    return [CocinaItemOut(id=i[0], nombre=i[1], cantidad=i[2], categoria=i[3], sabor_nombre=i[4], topping_nombre=i[5]) for i in items]


def _cocina_ordenes_de_ventas(conn, uid: int, categoria_ids: set[int] | None) -> list[CocinaOrdenOut]:
    rows = conn.run(COCINA_ORDENES_SELECT, uid=uid)
    ordenes = []
    for r in rows:
        item_rows = conn.run(COCINA_ITEMS_SELECT, id=r[0])
        items = _filtrar_items_por_categoria(item_rows, categoria_ids)
        if categoria_ids is not None and not items:
            continue
        ordenes.append(
            CocinaOrdenOut(
                id=r[0], tipo=r[1], estado=r[2], notas=r[3], fecha_apertura=r[4],
                mesa_numero=r[5], mesa_nombre=r[6], mesa_zona=r[7],
                items=items,
            )
        )
    return ordenes


def _cocina_ordenes_de_domicilios(conn, uid: int, categoria_ids: set[int] | None) -> list[CocinaOrdenOut]:
    rows = conn.run(DOMICILIO_ORDENES_SELECT, uid=uid)
    ordenes = []
    for r in rows:
        item_rows = conn.run(DOMICILIO_ITEMS_SELECT, id=r[0])
        items = _filtrar_items_por_categoria(item_rows, categoria_ids)
        if categoria_ids is not None and not items:
            continue
        ordenes.append(
            CocinaOrdenOut(
                id=r[0], tipo=r[1], estado=_ESTADO_DOMICILIO_A_COCINA[r[2]], notas=r[3] or "", fecha_apertura=r[4],
                items=items,
                origen="domicilio", cliente_nombre=r[5], direccion=r[6],
            )
        )
    return ordenes


def _orden_sort_key(orden: CocinaOrdenOut):
    # ventas.fecha_apertura trae zona horaria; domicilios.created_at no — sin normalizar,
    # comparar ambas revienta con "can't compare offset-naive and offset-aware datetimes".
    fecha = orden.fecha_apertura
    return fecha.replace(tzinfo=None) if fecha.tzinfo else fecha


def _categorias_del_cocinero(conn, current_user: UserOut) -> set[int] | None:
    """None = ve todo (no es cocina, o es cocina pero no tiene categorías asignadas — se queda
    con el comportamiento de siempre). Un set (aunque esté vacío) = filtrar a solo esas."""
    if current_user.rol != "cocina":
        return None
    rows = conn.run("SELECT categoria_id FROM usuario_categorias WHERE usuario_id = :id", id=current_user.id)
    ids = {r[0] for r in rows}
    return ids or None


@router.get("/cocina/ordenes", response_model=list[CocinaOrdenOut])
def cocina_ordenes(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        categoria_ids = _categorias_del_cocinero(conn, current_user)
        ordenes = _cocina_ordenes_de_ventas(conn, current_user.tenant_id, categoria_ids) + _cocina_ordenes_de_domicilios(
            conn, current_user.tenant_id, categoria_ids
        )
        ordenes.sort(key=_orden_sort_key)
        return ordenes
    finally:
        conn.close()


COCINA_HISTORIAL_SELECT = """
    SELECT ventas.id, ventas.tipo, ventas.estado, ventas.notas, ventas.fecha_apertura,
           mesas.numero AS mesa_numero, mesas.nombre AS mesa_nombre, zonas.key AS mesa_zona
    FROM ventas
    LEFT JOIN mesas ON mesas.id = ventas.mesa_id
    LEFT JOIN zonas ON zonas.id = mesas.zona_id
    WHERE ventas.usuario_id = :uid AND ventas.estado IN ('cerrada', 'cancelada', 'entregada')
      AND COALESCE(ventas.fecha_cierre, ventas.fecha_apertura)::date = :hoy
    ORDER BY COALESCE(ventas.fecha_cierre, ventas.fecha_apertura) DESC
"""

DOMICILIO_HISTORIAL_SELECT = """
    SELECT id, tipo, estado, notas, created_at, nombre_cliente, direccion
    FROM domicilios
    WHERE usuario_id = :uid AND estado IN ('entregado', 'cancelado')
      AND updated_at::date = :hoy
    ORDER BY updated_at DESC
"""

_ESTADO_DOMICILIO_A_HISTORIAL = {"entregado": "cerrada", "cancelado": "cancelada"}


@router.get("/cocina/historial", response_model=list[CocinaOrdenOut])
def cocina_historial(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        categoria_ids = _categorias_del_cocinero(conn, current_user)
        hoy = date.today()
        rows = conn.run(COCINA_HISTORIAL_SELECT, uid=current_user.tenant_id, hoy=hoy)
        ordenes = []
        for r in rows:
            item_rows = conn.run(COCINA_ITEMS_SELECT, id=r[0])
            items = _filtrar_items_por_categoria(item_rows, categoria_ids)
            if categoria_ids is not None and not items:
                continue
            ordenes.append(
                CocinaOrdenOut(
                    id=r[0], tipo=r[1], estado=r[2], notas=r[3], fecha_apertura=r[4],
                    mesa_numero=r[5], mesa_nombre=r[6], mesa_zona=r[7],
                    items=items,
                )
            )

        dom_rows = conn.run(DOMICILIO_HISTORIAL_SELECT, uid=current_user.tenant_id, hoy=hoy)
        for r in dom_rows:
            item_rows = conn.run(DOMICILIO_ITEMS_SELECT, id=r[0])
            items = _filtrar_items_por_categoria(item_rows, categoria_ids)
            if categoria_ids is not None and not items:
                continue
            ordenes.append(
                CocinaOrdenOut(
                    id=r[0], tipo=r[1], estado=_ESTADO_DOMICILIO_A_HISTORIAL[r[2]], notas=r[3] or "", fecha_apertura=r[4],
                    items=items,
                    origen="domicilio", cliente_nombre=r[5], direccion=r[6],
                )
            )
        return ordenes
    finally:
        conn.close()


VENTA_COLUMNS = [
    "id", "mesa_id", "tipo", "estado", "total", "descuento", "cupon_id", "cupon_codigo",
    "notas", "metodo_pago", "pago_efectivo", "pago_tarjeta", "pago_transferencia", "propina",
    "fecha_apertura", "fecha_cierre", "cliente_id", "numero_orden",
]
ITEM_COLUMNS = [
    "id", "receta_id", "nombre", "cantidad", "precio_unitario", "subtotal", "sabor_nombre", "topping_nombre",
]


def _row_to_item(row) -> VentaItemOut:
    d = dict(zip(ITEM_COLUMNS, row))
    return VentaItemOut(
        id=d["id"], receta_id=d["receta_id"], nombre=d["nombre"], cantidad=d["cantidad"],
        precio_unitario=float(d["precio_unitario"]), subtotal=float(d["subtotal"]), sabor_nombre=d["sabor_nombre"],
        topping_nombre=d["topping_nombre"],
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
    cliente_nombre = None
    if v["cliente_id"] is not None:
        cliente_rows = conn.run("SELECT nombre FROM clientes WHERE id = :id", id=v["cliente_id"])
        cliente_nombre = cliente_rows[0][0] if cliente_rows else None
    return VentaOut(
        id=v["id"],
        mesa_id=v["mesa_id"],
        tipo=v["tipo"],
        estado=v["estado"],
        total=float(v["total"]),
        descuento=float(v["descuento"]),
        cupon_codigo=v["cupon_codigo"],
        notas=v["notas"],
        metodo_pago=v["metodo_pago"],
        pago_efectivo=float(v["pago_efectivo"]),
        pago_tarjeta=float(v["pago_tarjeta"]),
        pago_transferencia=float(v["pago_transferencia"]),
        propina=float(v["propina"]),
        fecha_apertura=v["fecha_apertura"],
        fecha_cierre=v["fecha_cierre"],
        cliente_id=v["cliente_id"],
        cliente_nombre=cliente_nombre,
        numero_orden=v["numero_orden"],
        items=[_row_to_item(r) for r in item_rows],
    )


def _recalcular_total(conn, venta_id: int) -> None:
    """Recomputes both the discount and the total from scratch every time —
    called after any item or coupon change, so a percentage/product coupon
    always tracks the current cart instead of freezing a stale amount."""
    items = conn.run("SELECT receta_id, subtotal FROM venta_items WHERE venta_id = :id", id=venta_id)
    subtotal_total = sum(float(s) for _, s in items)

    cupon_id = conn.run("SELECT cupon_id FROM ventas WHERE id = :id", id=venta_id)[0][0]
    descuento = 0.0
    if cupon_id:
        cupon = conn.run("SELECT tipo, descuento, id_receta FROM cupones WHERE id = :id", id=cupon_id)
        if cupon:
            tipo, valor, id_receta = cupon[0][0], float(cupon[0][1]), cupon[0][2]
            if tipo == "porcentaje":
                descuento = subtotal_total * valor / 100
            elif tipo == "valor":
                descuento = min(valor, subtotal_total)
            elif tipo == "producto":
                base = sum(float(s) for rid, s in items if rid == id_receta)
                descuento = base * valor / 100

    descuento = round(descuento, 2)
    total = round(max(0.0, subtotal_total - descuento), 2)
    conn.run("UPDATE ventas SET descuento = :d, total = :t WHERE id = :id", d=descuento, t=total, id=venta_id)


def _consumo_de_receta(conn, receta_id: int, cantidad: float) -> dict[int, float]:
    """Cuánto de cada insumo necesitan `cantidad` unidades de esta receta."""
    filas = conn.run("SELECT id_insumo, cantidad FROM receta_insumos WHERE id_receta = :id", id=receta_id)
    return {id_insumo: float(cant_receta) * cantidad for id_insumo, cant_receta in filas}


def _consumo_de_topping(conn, topping_id: int, cantidad: float) -> dict[int, float]:
    """Cuánto de cada insumo necesitan `cantidad` unidades de este topping (ej. "Tocineta extra"
    consume bacon real del inventario, igual que una receta)."""
    filas = conn.run("SELECT id_insumo, cantidad FROM topping_insumos WHERE id_topping = :id", id=topping_id)
    return {id_insumo: float(cant_topping) * cantidad for id_insumo, cant_topping in filas}


def _sumar_consumo(a: dict[int, float], b: dict[int, float]) -> dict[int, float]:
    """Combina dos consumos de insumos (ej. el de la receta base y el de su topping)."""
    resultado = dict(a)
    for id_insumo, cantidad in b.items():
        resultado[id_insumo] = resultado.get(id_insumo, 0.0) + cantidad
    return resultado


def _consumo_de_item(conn, receta_id: int | None, topping_id: int | None, cantidad: float) -> dict[int, float]:
    """Consumo total de un ítem de venta: insumos de la receta base más los del topping elegido,
    si tiene uno."""
    consumo = _consumo_de_receta(conn, receta_id, cantidad) if receta_id is not None else {}
    if topping_id is not None:
        consumo = _sumar_consumo(consumo, _consumo_de_topping(conn, topping_id, cantidad))
    return consumo


def _consumir_stock(conn, consumo: dict[int, float]) -> None:
    """Descuenta stock para estos insumos, bloqueando sus filas (FOR UPDATE) para que dos
    pedidos concurrentes por el mismo ingrediente no pasen ambos la validación antes de que
    ninguno haya descontado nada. Lanza 409 si no alcanza. Se llama al agregar/aumentar un
    ítem (reserva inmediata), no al cobrar — así la cocina nunca prepara algo que después
    el sistema se niegue a cobrar por falta de stock."""
    if not consumo:
        return
    for id_insumo, requerido in consumo.items():
        fila = conn.run("SELECT nombre, cantidad_stock FROM insumos WHERE id = :id FOR UPDATE", id=id_insumo)
        if not fila:
            continue
        nombre, stock_actual = fila[0][0], float(fila[0][1])
        if stock_actual < requerido:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Stock insuficiente de \"{nombre}\"")
    for id_insumo, requerido in consumo.items():
        conn.run(
            "UPDATE insumos SET cantidad_stock = cantidad_stock - :cant WHERE id = :id",
            cant=requerido, id=id_insumo,
        )


def _restituir_stock(conn, consumo: dict[int, float]) -> None:
    """Devuelve al stock lo reservado por un ítem que se quita, se reduce o cuya orden se cancela."""
    for id_insumo, cantidad in consumo.items():
        conn.run(
            "UPDATE insumos SET cantidad_stock = cantidad_stock + :cant WHERE id = :id",
            cant=cantidad, id=id_insumo,
        )


def _liberar_mesa_si_corresponde(conn, mesa_id: int | None) -> None:
    if mesa_id is None:
        return
    activas = conn.run(
        "SELECT 1 FROM ventas WHERE mesa_id = :mid AND estado IN ('abierta', 'en_preparacion', 'lista', 'entregada')",
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
    tipo: str = Query(default=""),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    propias: bool = Query(default=False),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        hoy = date.today()
        desde = desde or hoy
        hasta = hasta or hoy
        items: list[VentaListadoItemOut] = []

        if tipo in ("", "mesa", "directa"):
            clauses = ["v.usuario_id = :uid", "v.fecha_apertura::date BETWEEN :desde AND :hasta"]
            params: dict = {"uid": current_user.tenant_id, "desde": desde, "hasta": hasta}
            if propias:
                clauses.append("v.creado_por_id = :cid")
                params["cid"] = current_user.id
            if estado:
                clauses.append("v.estado = :estado")
                params["estado"] = estado
            if tipo:
                clauses.append("v.tipo = :tipo")
                params["tipo"] = tipo
            if buscar.strip():
                clauses.append(
                    "(CAST(v.id AS TEXT) ILIKE :buscar OR CAST(m.numero AS TEXT) ILIKE :buscar "
                    "OR v.numero_orden ILIKE :buscar)"
                )
                params["buscar"] = f"%{buscar.strip()}%"
            where_sql = " AND ".join(clauses)

            rows = conn.run(
                f"SELECT v.id, v.fecha_apertura, v.tipo, v.estado, m.numero AS mesa_numero, "
                f"COALESCE(ic.cnt, 0) AS platos, v.total, v.metodo_pago, v.numero_orden "
                f"FROM ventas v "
                f"LEFT JOIN mesas m ON m.id = v.mesa_id "
                f"LEFT JOIN (SELECT venta_id, COALESCE(SUM(cantidad), 0) AS cnt FROM venta_items GROUP BY venta_id) ic "
                f"ON ic.venta_id = v.id "
                f"WHERE {where_sql} "
                f"ORDER BY v.fecha_apertura DESC",
                **params,
            )
            items = [
                VentaListadoItemOut(
                    id=r[0], fecha=r[1], tipo=r[2], estado=r[3], mesa_numero=r[4],
                    platos=r[5], total=float(r[6]), metodo_pago=r[7] or None,
                    numero_orden=r[8] or f"#{r[0]}",
                )
                for r in rows
            ]

        # Los domicilios entregados cuentan como una venta más (cerrada): no tienen mesa ni
        # "creado_por_id", así que se dejan afuera si se filtra por "mis ventas", por un
        # estado que no sea el de cerrada/cobrada, o por un tipo que no sea "domicilio".
        if tipo in ("", "domicilio") and not propias and estado in ("", "cerrada"):
            d_clauses = [
                "d.usuario_id = :uid", "d.estado = 'entregado'", "d.created_at::date BETWEEN :desde AND :hasta",
            ]
            d_params: dict = {"uid": current_user.tenant_id, "desde": desde, "hasta": hasta}
            if buscar.strip():
                d_clauses.append("(CAST(d.id AS TEXT) ILIKE :buscar OR d.nombre_cliente ILIKE :buscar)")
                d_params["buscar"] = f"%{buscar.strip()}%"
            d_rows = conn.run(
                f"SELECT d.id, d.created_at, COALESCE(ic.cnt, 0) AS platos, d.total, d.metodo_pago "
                f"FROM domicilios d "
                f"LEFT JOIN (SELECT domicilio_id, COALESCE(SUM(cantidad), 0) AS cnt FROM domicilio_items GROUP BY domicilio_id) ic "
                f"ON ic.domicilio_id = d.id "
                f"WHERE {' AND '.join(d_clauses)}",
                **d_params,
            )
            items += [
                VentaListadoItemOut(
                    id=r[0], fecha=r[1], tipo="domicilio", estado="cerrada", mesa_numero=None,
                    platos=r[2], total=float(r[3]), metodo_pago=r[4] or None,
                    numero_orden=f"DOM-{r[0]}",
                )
                for r in d_rows
            ]

        # ventas.fecha_apertura trae zona horaria; domicilios.created_at no — sin normalizar,
        # comparar ambas revienta con "can't compare offset-naive and offset-aware datetimes".
        items.sort(key=lambda i: i.fecha.replace(tzinfo=None) if i.fecha.tzinfo else i.fecha, reverse=True)
        total = len(items)
        monto_total = sum(i.total for i in items)
        total_paginas = max(1, -(-total // POR_PAGINA))
        offset = (pagina - 1) * POR_PAGINA
        items = items[offset: offset + POR_PAGINA]

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
            "AND estado IN ('abierta','en_preparacion','lista','entregada') ORDER BY fecha_apertura",
            mid=mesa_id, uid=current_user.tenant_id,
        )
        return [_get_venta_con_items(conn, current_user.tenant_id, r[0]) for r in rows]
    finally:
        conn.close()


@router.post("/ventas/mesa/{mesa_id}/cambiar", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_de_mesa(mesa_id: int, payload: MesaCambioIn, current_user: UserOut = Depends(get_current_user)):
    if payload.destino_id == mesa_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Elige una mesa distinta a la actual")
    conn = get_connection()
    try:
        uid = current_user.tenant_id
        origen = conn.run("SELECT id FROM mesas WHERE id = :id AND usuario_id = :uid", id=mesa_id, uid=uid)
        if not origen:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")
        destino = conn.run(
            "SELECT estado, activo FROM mesas WHERE id = :id AND usuario_id = :uid", id=payload.destino_id, uid=uid
        )
        if not destino:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La mesa destino no existe")
        if not destino[0][1] or destino[0][0] != "disponible":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La mesa destino no está libre")
        activas_destino = conn.run(
            "SELECT 1 FROM ventas WHERE mesa_id = :mid AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista','entregada')",
            mid=payload.destino_id, uid=uid,
        )
        if activas_destino:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La mesa destino ya tiene una orden abierta")
        movidas = conn.run(
            "UPDATE ventas SET mesa_id = :dest WHERE mesa_id = :orig AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista','entregada') RETURNING id",
            dest=payload.destino_id, orig=mesa_id, uid=uid,
        )
        if not movidas:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La mesa no tiene una orden para mover")
        conn.run("UPDATE mesas SET estado = 'ocupada' WHERE id = :id", id=payload.destino_id)
        _liberar_mesa_si_corresponde(conn, mesa_id)
    finally:
        conn.close()


@router.post("/ventas", response_model=VentaOut, status_code=status.HTTP_201_CREATED)
def abrir_orden(payload: VentaCrearIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        if payload.mesa_id is None:
            numero_orden = generar_numero_orden(conn, current_user.tenant_id)
            rows = conn.run(
                "INSERT INTO ventas (mesa_id, tipo, estado, usuario_id, creado_por_id, numero_orden) "
                "VALUES (NULL, 'directa', 'abierta', :uid, :cid, :numero) "
                f"RETURNING {', '.join(VENTA_COLUMNS)}",
                uid=current_user.tenant_id, cid=current_user.id, numero=numero_orden,
            )
            return _get_venta_con_items(conn, current_user.tenant_id, rows[0][0])

        mesa = conn.run(
            "SELECT estado, activo FROM mesas WHERE id = :id AND usuario_id = :uid",
            id=payload.mesa_id, uid=current_user.tenant_id,
        )
        if not mesa:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")
        estado_mesa, activo_mesa = mesa[0]

        existente = conn.run(
            "SELECT id FROM ventas WHERE mesa_id = :mid AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista','entregada') ORDER BY fecha_apertura LIMIT 1",
            mid=payload.mesa_id, uid=current_user.tenant_id,
        )
        if existente:
            # Ya hay una cuenta abierta en esta mesa: se reutiliza sin importar qué diga
            # `estado` (se autocorrige abajo), para no bloquear una mesa que ya se auto-saneará.
            return _get_venta_con_items(conn, current_user.tenant_id, existente[0][0])

        if not activo_mesa:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta mesa está desactivada")
        if estado_mesa in ("reservada", "mantenimiento"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La mesa está {estado_mesa}; cambia su estado antes de abrir una orden",
            )

        numero_orden = generar_numero_orden(conn, current_user.tenant_id)
        rows = conn.run(
            "INSERT INTO ventas (mesa_id, tipo, estado, usuario_id, creado_por_id, numero_orden) "
            "VALUES (:mesa_id, 'mesa', 'abierta', :uid, :cid, :numero) "
            f"RETURNING {', '.join(VENTA_COLUMNS)}",
            mesa_id=payload.mesa_id,
            uid=current_user.tenant_id,
            cid=current_user.id,
            numero=numero_orden,
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

        sabor_nombre = None
        sabor_extra = 0.0
        if payload.sabor_id is not None:
            sabor = conn.run(
                "SELECT s.nombre, rs.precio_adicional FROM receta_sabores rs JOIN sabores s ON s.id = rs.id_sabor "
                "WHERE rs.id_receta = :rid AND s.id = :sid",
                rid=payload.receta_id, sid=payload.sabor_id,
            )
            if not sabor:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese sabor no está disponible para esta receta")
            sabor_nombre = sabor[0][0]
            sabor_extra = float(sabor[0][1])

        topping_nombre = None
        topping_extra = 0.0
        if payload.topping_id is not None:
            topping = conn.run(
                "SELECT t.nombre, rt.precio_adicional FROM receta_toppings rt JOIN toppings t ON t.id = rt.id_topping "
                "WHERE rt.id_receta = :rid AND t.id = :tid",
                rid=payload.receta_id, tid=payload.topping_id,
            )
            if not topping:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese topping no está disponible para esta receta")
            topping_nombre = topping[0][0]
            topping_extra = float(topping[0][1])

        # El valor adicional del sabor y/o el topping (si tienen) se suma al precio de venta de
        # la receta para formar el precio unitario real de esta línea.
        precio_unitario = precio_venta + sabor_extra + topping_extra

        consumo = _consumo_de_item(conn, payload.receta_id, payload.topping_id, payload.cantidad)

        conn.run("BEGIN")
        try:
            _consumir_stock(conn, consumo)

            # Dos sabores/toppings del mismo plato son líneas distintas: no se suman entre sí.
            existente = conn.run(
                "SELECT id, cantidad FROM venta_items WHERE venta_id = :vid AND receta_id = :rid "
                "AND sabor_id IS NOT DISTINCT FROM :sid AND topping_id IS NOT DISTINCT FROM :tid",
                vid=venta_id,
                rid=payload.receta_id,
                sid=payload.sabor_id,
                tid=payload.topping_id,
            )
            if existente:
                item_id, cantidad_actual = existente[0]
                nueva_cantidad = cantidad_actual + payload.cantidad
                conn.run(
                    "UPDATE venta_items SET cantidad = :cant, subtotal = :subtotal WHERE id = :id",
                    cant=nueva_cantidad,
                    subtotal=round(nueva_cantidad * precio_unitario, 2),
                    id=item_id,
                )
            else:
                subtotal = round(payload.cantidad * precio_unitario, 2)
                conn.run(
                    "INSERT INTO venta_items (venta_id, receta_id, nombre, cantidad, precio_unitario, subtotal, "
                    "sabor_id, sabor_nombre, topping_id, topping_nombre) "
                    "VALUES (:vid, :rid, :nombre, :cant, :precio, :subtotal, :sid, :sabor_nombre, :tid, :topping_nombre)",
                    vid=venta_id,
                    rid=payload.receta_id,
                    nombre=nombre,
                    cant=payload.cantidad,
                    precio=precio_unitario,
                    subtotal=subtotal,
                    sid=payload.sabor_id,
                    sabor_nombre=sabor_nombre,
                    tid=payload.topping_id,
                    topping_nombre=topping_nombre,
                )
            # Un pedido nuevo en una orden ya servida/lista es comida que falta por preparar:
            # vuelve a "abierta" para que cocina la vea de nuevo en su tablero.
            if venta["estado"] in ("lista", "entregada"):
                conn.run("UPDATE ventas SET estado = 'abierta' WHERE id = :id", id=venta_id)
            _recalcular_total(conn, venta_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
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
            "SELECT receta_id, topping_id, precio_unitario, cantidad FROM venta_items WHERE id = :iid AND venta_id = :vid",
            iid=item_id,
            vid=venta_id,
        )
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
        receta_id, topping_id, precio_unitario, cantidad_actual = item[0]
        delta = payload.cantidad - cantidad_actual

        conn.run("BEGIN")
        try:
            if (receta_id is not None or topping_id is not None) and delta != 0:
                consumo_delta = _consumo_de_item(conn, receta_id, topping_id, abs(delta))
                if delta > 0:
                    _consumir_stock(conn, consumo_delta)
                else:
                    _restituir_stock(conn, consumo_delta)

            conn.run(
                "UPDATE venta_items SET cantidad = :cant, subtotal = :subtotal WHERE id = :id",
                cant=payload.cantidad,
                subtotal=round(payload.cantidad * float(precio_unitario), 2),
                id=item_id,
            )
            # Pedir más de algo ya servido/listo es comida nueva por preparar.
            if delta > 0 and venta["estado"] in ("lista", "entregada"):
                conn.run("UPDATE ventas SET estado = 'abierta' WHERE id = :id", id=venta_id)
            _recalcular_total(conn, venta_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.delete("/ventas/{venta_id}/items/{item_id}", response_model=VentaOut)
def eliminar_item(venta_id: int, item_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        item = conn.run(
            "SELECT receta_id, topping_id, cantidad FROM venta_items WHERE id = :iid AND venta_id = :vid",
            iid=item_id, vid=venta_id,
        )
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
        receta_id, topping_id, cantidad = item[0]

        conn.run("BEGIN")
        try:
            conn.run("DELETE FROM venta_items WHERE id = :iid AND venta_id = :vid", iid=item_id, vid=venta_id)
            if receta_id is not None or topping_id is not None:
                _restituir_stock(conn, _consumo_de_item(conn, receta_id, topping_id, cantidad))
            _recalcular_total(conn, venta_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
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


@router.patch("/ventas/{venta_id}/cliente", response_model=VentaOut)
def asignar_cliente(venta_id: int, payload: VentaClienteIn, current_user: UserOut = Depends(get_current_user)):
    """A quién va la factura/comanda: se puede poner o quitar en cualquier estado de la
    venta, incluso ya cobrada, porque a veces se decide al momento de imprimir."""
    conn = get_connection()
    try:
        _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if payload.cliente_id is not None:
            cliente = conn.run(
                "SELECT 1 FROM clientes WHERE id = :id AND usuario_id = :uid",
                id=payload.cliente_id, uid=current_user.tenant_id,
            )
            if not cliente:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
        conn.run("UPDATE ventas SET cliente_id = :cid WHERE id = :id", cid=payload.cliente_id, id=venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.post("/ventas/{venta_id}/cupon", response_model=VentaOut)
def aplicar_cupon(venta_id: int, payload: VentaCuponIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        codigo = payload.codigo.strip().upper()
        rows = conn.run(
            "SELECT id, tipo, descuento, usos_max, usos_actual, estado, expira_en, id_receta "
            "FROM cupones WHERE usuario_id = :uid AND codigo = :c",
            uid=current_user.tenant_id, c=codigo,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cupón no válido")

        cupon_id, tipo, valor, usos_max, usos_actual, estado_cupon, expira_en, id_receta = rows[0]
        if estado_cupon != "activo":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese cupón no está activo")
        if expira_en and expira_en < date.today():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese cupón ya expiró")
        if usos_actual >= usos_max:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese cupón ya alcanzó su límite de usos")

        if tipo == "producto":
            items = conn.run(
                "SELECT 1 FROM venta_items WHERE venta_id = :id AND receta_id = :rid", id=venta_id, rid=id_receta
            )
            if not items:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Este cupón aplica a un producto que no está en la orden",
                )

        conn.run(
            "UPDATE ventas SET cupon_id = :cid, cupon_codigo = :codigo WHERE id = :id",
            cid=cupon_id, codigo=codigo, id=venta_id,
        )
        _recalcular_total(conn, venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


@router.delete("/ventas/{venta_id}/cupon", response_model=VentaOut)
def quitar_cupon(venta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")
        conn.run("UPDATE ventas SET cupon_id = NULL, cupon_codigo = NULL WHERE id = :id", id=venta_id)
        _recalcular_total(conn, venta_id)
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


# Solo avanza, nunca retrocede: "lista" no puede volver a "en_preparacion" vía esta ruta.
# "entregada" = ya se sirvió en la mesa; la cuenta sigue abierta (puede seguir pidiendo),
# pero cocina ya no necesita verla en su tablero.
_TRANSICIONES_VENTA_COCINA = {
    "abierta": {"en_preparacion"},
    "en_preparacion": {"lista"},
    "lista": {"entregada"},
}


@router.patch("/ventas/{venta_id}/estado", response_model=VentaOut)
def cambiar_estado_cocina(venta_id: int, payload: VentaEstadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if payload.estado not in _TRANSICIONES_VENTA_COCINA.get(venta["estado"], set()):
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
            "SELECT 1 FROM venta_items WHERE venta_id = :id AND receta_id IS NOT NULL LIMIT 1",
            id=venta_id,
        )
        if not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La orden no tiene ítems para cobrar")

        # El stock de cada ítem ya se reservó al agregarlo a la orden (ver agregar_item/
        # actualizar_cantidad_item), así que cobrar no vuelve a tocarlo — evita que dos mesas
        # puedan "pasar" la validación de stock al mismo tiempo y solo una logre cobrar después
        # de que cocina ya preparó ambas.
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

        if venta["cupon_id"]:
            conn.run(
                "UPDATE cupones SET usos_actual = usos_actual + 1 WHERE id = :id", id=venta["cupon_id"]
            )
            conn.run(
                "UPDATE cupones SET estado = 'usado' WHERE id = :id AND usos_actual >= usos_max",
                id=venta["cupon_id"],
            )
            conn.run(
                "INSERT INTO cupones_usos (id_cupon, codigo, monto_descuento) VALUES (:id, :codigo, :monto)",
                id=venta["cupon_id"], codigo=venta["cupon_codigo"], monto=venta["descuento"],
            )

        _liberar_mesa_si_corresponde(conn, venta["mesa_id"])
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()


PAGO_COLUMNS = ["id", "metodo_pago", "monto", "propina", "created_at"]


def _pagos_divididos_out(conn, venta: dict) -> VentaCuentaDivididaOut:
    rows = conn.run(
        f"SELECT {', '.join(PAGO_COLUMNS)} FROM venta_pagos WHERE venta_id = :id ORDER BY created_at",
        id=venta["id"],
    )
    pagos = [
        VentaPagoOut(id=r[0], metodo_pago=r[1], monto=float(r[2]), propina=float(r[3]), created_at=r[4])
        for r in rows
    ]
    total = float(venta["total"])
    pagado = sum(p.monto for p in pagos)
    return VentaCuentaDivididaOut(
        venta_id=venta["id"], total=total, pagado=pagado, restante=max(0.0, round(total - pagado, 2)),
        cerrada=venta["estado"] == "cerrada", pagos=pagos,
    )


@router.get("/ventas/{venta_id}/pagos", response_model=VentaCuentaDivididaOut)
def listar_pagos_divididos(venta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        return _pagos_divididos_out(conn, venta)
    finally:
        conn.close()


@router.post("/ventas/{venta_id}/pagos", response_model=VentaCuentaDivididaOut, status_code=status.HTTP_201_CREATED)
def registrar_pago_dividido(
    venta_id: int, payload: VentaPagoIn, current_user: UserOut = Depends(get_current_user)
):
    """Registra lo que pagó una persona de una cuenta dividida. Cuando la suma de los pagos
    alcanza el total, la venta se cierra sola — mismo efecto final que /cobrar, pero en varios
    pasos y permitiendo un método de pago distinto por persona."""
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        items = conn.run(
            "SELECT 1 FROM venta_items WHERE venta_id = :id AND receta_id IS NOT NULL LIMIT 1", id=venta_id
        )
        if not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La orden no tiene ítems para cobrar")

        estado_actual = _pagos_divididos_out(conn, venta)
        if payload.monto > estado_actual.restante + 0.01:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ese monto supera lo que falta por pagar (restante: {estado_actual.restante})",
            )

        conn.run(
            "INSERT INTO venta_pagos (venta_id, metodo_pago, monto, propina) VALUES (:id, :mp, :monto, :prop)",
            id=venta_id, mp=payload.metodo_pago, monto=payload.monto, prop=payload.propina,
        )

        nuevo_estado = _pagos_divididos_out(conn, venta)
        if nuevo_estado.restante <= 0.01:
            pagos_rows = conn.run(
                "SELECT metodo_pago, monto, propina FROM venta_pagos WHERE venta_id = :id", id=venta_id
            )
            metodos_usados = {r[0] for r in pagos_rows}
            metodo_final = metodos_usados.pop() if len(metodos_usados) == 1 else "mixto"
            propina_total = sum(float(r[2]) for r in pagos_rows)
            pe = sum(float(r[1]) for r in pagos_rows if r[0] == "efectivo")
            pt = sum(float(r[1]) for r in pagos_rows if r[0] == "tarjeta")
            ptr = sum(float(r[1]) for r in pagos_rows if r[0] == "transferencia")

            conn.run(
                "UPDATE ventas SET estado = 'cerrada', fecha_cierre = now(), metodo_pago = :mp, "
                "pago_efectivo = :pe, pago_tarjeta = :pt, pago_transferencia = :ptr, propina = :prop "
                "WHERE id = :id",
                mp=metodo_final, pe=pe, pt=pt, ptr=ptr, prop=propina_total, id=venta_id,
            )
            if venta["cupon_id"]:
                conn.run("UPDATE cupones SET usos_actual = usos_actual + 1 WHERE id = :id", id=venta["cupon_id"])
                conn.run(
                    "UPDATE cupones SET estado = 'usado' WHERE id = :id AND usos_actual >= usos_max",
                    id=venta["cupon_id"],
                )
                conn.run(
                    "INSERT INTO cupones_usos (id_cupon, codigo, monto_descuento) VALUES (:id, :codigo, :monto)",
                    id=venta["cupon_id"], codigo=venta["cupon_codigo"], monto=venta["descuento"],
                )
            _liberar_mesa_si_corresponde(conn, venta["mesa_id"])
            venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)

        return _pagos_divididos_out(conn, venta)
    finally:
        conn.close()


@router.delete("/ventas/{venta_id}", response_model=VentaOut)
def cancelar_orden(venta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        venta = _get_venta_or_404(conn, current_user.tenant_id, venta_id)
        if venta["estado"] not in ACTIVOS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta orden ya está cerrada")

        items = conn.run(
            "SELECT receta_id, topping_id, cantidad FROM venta_items WHERE venta_id = :id "
            "AND (receta_id IS NOT NULL OR topping_id IS NOT NULL)",
            id=venta_id,
        )
        conn.run("BEGIN")
        try:
            # El stock de cada ítem se había reservado al agregarlo (incluso si cocina ya lo
            # preparó); cancelar la orden lo devuelve, sin importar en qué estado se cancele.
            for receta_id, topping_id, cantidad in items:
                _restituir_stock(conn, _consumo_de_item(conn, receta_id, topping_id, cantidad))
            conn.run("UPDATE ventas SET estado = 'cancelada', fecha_cierre = now() WHERE id = :id", id=venta_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        _liberar_mesa_si_corresponde(conn, venta["mesa_id"])
        return _get_venta_con_items(conn, current_user.tenant_id, venta_id)
    finally:
        conn.close()
