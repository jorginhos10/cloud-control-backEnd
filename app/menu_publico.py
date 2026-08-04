from fastapi import APIRouter, HTTPException, status

from app.database import get_connection
from app.schemas import MenuDigitalDetalleOut, OrdenPublicaOut, PedidoIn, PedidoOut, VentaItemOut
from app.menu_digital import _get_items, _row_to_menu

router = APIRouter(prefix="/menu")

ACTIVOS = ("abierta", "en_preparacion", "lista")

MENU_PUBLICO_SELECT = """
    SELECT md.id, md.nombre, md.descripcion, md.activo, md.token, md.mesa_id,
           m.numero AS mesa_numero, m.nombre AS mesa_nombre, md.created_at, 0, md.usuario_id
    FROM menus_digitales md
    LEFT JOIN mesas m ON m.id = md.mesa_id
    WHERE md.token = :token
"""
MENU_COLUMNS = [
    "id", "nombre", "descripcion", "activo", "token", "mesa_id",
    "mesa_numero", "mesa_nombre", "created_at", "items_count", "usuario_id",
]


def _get_menu_por_token(conn, token: str) -> dict:
    rows = conn.run(MENU_PUBLICO_SELECT, token=token)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menú no encontrado")
    row = dict(zip(MENU_COLUMNS, rows[0]))
    if not row["activo"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este menú no está disponible")
    return row


@router.get("/{token}", response_model=MenuDigitalDetalleOut)
def ver_menu(token: str):
    conn = get_connection()
    try:
        row = _get_menu_por_token(conn, token)
        return MenuDigitalDetalleOut(**_row_to_menu(row).model_dump(), items=_get_items(conn, row["id"]))
    finally:
        conn.close()


@router.post("/{token}/pedido", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def hacer_pedido(token: str, payload: PedidoIn):
    conn = get_connection()
    try:
        menu = _get_menu_por_token(conn, token)
        if menu["mesa_id"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este menú es solo de consulta y no permite pedidos",
            )
        if not payload.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El pedido no tiene ítems")

        items_del_menu = {r[0] for r in conn.run("SELECT receta_id FROM menu_items WHERE menu_id = :id", id=menu["id"])}

        existente = conn.run(
            "SELECT id FROM ventas WHERE mesa_id = :mid AND usuario_id = :uid "
            "AND estado IN ('abierta','en_preparacion','lista') ORDER BY fecha_apertura LIMIT 1",
            mid=menu["mesa_id"], uid=menu["usuario_id"],
        )
        if existente:
            venta_id = existente[0][0]
        else:
            rows = conn.run(
                "INSERT INTO ventas (mesa_id, tipo, estado, usuario_id) VALUES (:mesa_id, 'mesa', 'abierta', :uid) "
                "RETURNING id",
                mesa_id=menu["mesa_id"], uid=menu["usuario_id"],
            )
            venta_id = rows[0][0]
            conn.run("UPDATE mesas SET estado = 'ocupada' WHERE id = :id", id=menu["mesa_id"])

        pedido: dict[int, int] = {}
        for item in payload.items:
            if item.receta_id not in items_del_menu:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uno de los ítems no pertenece a este menú")
            pedido[item.receta_id] = pedido.get(item.receta_id, 0) + item.cantidad

        for receta_id, cantidad in pedido.items():
            receta = conn.run(
                "SELECT nombre, precio_venta FROM recetas WHERE id = :id AND activo = true", id=receta_id
            )
            if not receta:
                continue
            nombre, precio_venta = receta[0][0], float(receta[0][1])

            disponible = conn.run(
                "SELECT MIN(FLOOR(i.cantidad_stock / ri.cantidad)) FROM receta_insumos ri "
                "JOIN insumos i ON i.id = ri.id_insumo WHERE ri.id_receta = :id",
                id=receta_id,
            )[0][0]
            if disponible is not None:
                ya_en_carrito = conn.run(
                    "SELECT COALESCE(SUM(cantidad), 0) FROM venta_items WHERE venta_id = :vid AND receta_id = :rid",
                    vid=venta_id, rid=receta_id,
                )[0][0]
                if cantidad > int(disponible) - int(ya_en_carrito):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Stock insuficiente para \"{nombre}\"",
                    )

            existente_item = conn.run(
                "SELECT id, cantidad FROM venta_items WHERE venta_id = :vid AND receta_id = :rid",
                vid=venta_id, rid=receta_id,
            )
            if existente_item:
                item_id, cant_actual = existente_item[0]
                nueva = cant_actual + cantidad
                conn.run(
                    "UPDATE venta_items SET cantidad = :cant, subtotal = :subtotal WHERE id = :id",
                    cant=nueva, subtotal=round(nueva * precio_venta, 2), id=item_id,
                )
            else:
                conn.run(
                    "INSERT INTO venta_items (venta_id, receta_id, nombre, cantidad, precio_unitario, subtotal) "
                    "VALUES (:vid, :rid, :nombre, :cant, :precio, :subtotal)",
                    vid=venta_id, rid=receta_id, nombre=nombre, cant=cantidad, precio=precio_venta,
                    subtotal=round(cantidad * precio_venta, 2),
                )

        conn.run(
            "UPDATE ventas SET total = (SELECT COALESCE(SUM(subtotal), 0) FROM venta_items WHERE venta_id = :id) "
            "WHERE id = :id",
            id=venta_id,
        )
        venta = conn.run("SELECT estado, total FROM ventas WHERE id = :id", id=venta_id)[0]
        return PedidoOut(venta_id=venta_id, estado=venta[0], total=float(venta[1]))
    finally:
        conn.close()


@router.get("/{token}/pedido/{venta_id}", response_model=OrdenPublicaOut)
def estado_pedido(token: str, venta_id: int):
    conn = get_connection()
    try:
        menu = _get_menu_por_token(conn, token)
        rows = conn.run(
            "SELECT id, estado, total FROM ventas WHERE id = :id AND mesa_id = :mesa_id AND usuario_id = :uid",
            id=venta_id, mesa_id=menu["mesa_id"], uid=menu["usuario_id"],
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
        venta_id_db, estado, total = rows[0]

        item_rows = conn.run(
            "SELECT id, receta_id, nombre, cantidad, precio_unitario, subtotal FROM venta_items "
            "WHERE venta_id = :id ORDER BY creado_en",
            id=venta_id_db,
        )
        items = [
            VentaItemOut(
                id=r[0], receta_id=r[1], nombre=r[2], cantidad=r[3],
                precio_unitario=float(r[4]), subtotal=float(r[5]),
            )
            for r in item_rows
        ]
        return OrdenPublicaOut(id=venta_id_db, estado=estado, total=float(total), items=items)
    finally:
        conn.close()
