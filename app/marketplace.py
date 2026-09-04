import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import wompi
from app.auth import UserOut, get_current_user
from app.database import get_connection, get_superadmin_connection
from app.ingresos import _crear_ingreso
from app.schemas import (
    ConfirmarTransaccionIn,
    CuponValidarIn,
    CuponValidarOut,
    IngresoItemIn,
    ListaCompraEstadisticasOut,
    ListaCompraIn,
    ListaCompraItemOut,
    ListaCompraOut,
    MarketplaceItemOut,
    PedidoConCheckoutOut,
    PedidoIn,
    PedidoItemOut,
    PedidoOut,
    TiendaOut,
    WompiCheckoutOut,
)

router = APIRouter(prefix="/marketplace", dependencies=[Depends(get_current_user)])

PEDIDO_COLUMNS = [
    "id", "tienda_id", "tienda_nombre", "subtotal", "descuento", "total",
    "cupon_codigo", "estado", "wompi_reference", "wompi_transaction_id", "created_at",
]
PEDIDO_ITEM_COLUMNS = ["id", "producto_id", "nombre", "categoria", "precio_unitario", "cantidad", "subtotal"]

LISTA_COLUMNS = ["id", "numero", "estado", "notas", "total", "ingreso_id", "created_at", "updated_at"]
ITEM_COLUMNS = ["id", "insumo_id", "nombre", "cantidad", "precio_unitario", "subtotal"]


def _generar_numero(conn, usuario_id: int) -> str:
    hoy = date.today().strftime("%Y%m%d")
    count = conn.run(
        "SELECT COUNT(*) FROM listas_compra WHERE usuario_id = :uid AND numero LIKE :prefijo",
        uid=usuario_id, prefijo=f"LC-{hoy}-%",
    )[0][0]
    return f"LC-{hoy}-{count + 1:04d}"


def _get_items(conn, lista_id: int) -> list[ListaCompraItemOut]:
    rows = conn.run(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM lista_compra_items WHERE lista_id = :id ORDER BY id",
        id=lista_id,
    )
    return [
        ListaCompraItemOut(
            id=r[0], insumo_id=r[1], nombre=r[2],
            cantidad=float(r[3]), precio_unitario=float(r[4]), subtotal=float(r[5]),
        )
        for r in rows
    ]


def _row_to_lista(conn, row: dict) -> ListaCompraOut:
    return ListaCompraOut(
        id=row["id"], numero=row["numero"], estado=row["estado"], notas=row["notas"] or "",
        total=float(row["total"]), ingreso_id=row["ingreso_id"],
        created_at=row["created_at"], updated_at=row["updated_at"], items=_get_items(conn, row["id"]),
    )


def _get_lista_or_404(conn, usuario_id: int, lista_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(LISTA_COLUMNS)} FROM listas_compra WHERE id = :id AND usuario_id = :uid",
        id=lista_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista no encontrada")
    return dict(zip(LISTA_COLUMNS, rows[0]))


@router.get("/tiendas", response_model=list[TiendaOut])
def tiendas(current_user: UserOut = Depends(get_current_user)):
    """Rappi-style storefronts. Restaurants only ever buy here — they don't
    sell, so their own inventory is never listed as a "store" (it stays on
    the Insumos page). Right now every store is curated by the SuperAdmin;
    supplier-registered stores (a separate app for insumos providers) will
    join this list later via the same `tiendas` table."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return []

    try:
        rows = sconn.run(
            """
            SELECT t.id, t.nombre, t.descripcion, t.categoria, t.color,
                (SELECT COUNT(*) FROM marketplace_productos p WHERE p.tienda_id = t.id AND p.activo = true) AS total
            FROM tiendas t
            WHERE t.activo = true
            ORDER BY t.nombre
            """
        )
        return [
            TiendaOut(
                id=f"global:{r[0]}", nombre=r[1], descripcion=r[2], categoria=r[3], color=r[4],
                total_productos=r[5],
            )
            for r in rows
        ]
    finally:
        sconn.close()


@router.get("/tiendas/global/{tienda_id}/productos", response_model=list[MarketplaceItemOut])
def productos_tienda_global(tienda_id: int, current_user: UserOut = Depends(get_current_user)):
    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="El catálogo global no está disponible")

    try:
        rows = sconn.run(
            "SELECT id, nombre, categoria, unidad, precio "
            "FROM marketplace_productos WHERE tienda_id = :tid AND activo = true ORDER BY nombre",
            tid=tienda_id,
        )
        return [
            MarketplaceItemOut(
                id=r[0], nombre=r[1], categoria=r[2], unidad_medida=r[3], precio_unitario=float(r[4]),
            )
            for r in rows
        ]
    finally:
        sconn.close()


def _validar_cupon(sconn, codigo: str, subtotal: float) -> CuponValidarOut:
    codigo = codigo.strip().upper()
    if not codigo:
        return CuponValidarOut(valido=False, mensaje="Código vacío")

    rows = sconn.run(
        "SELECT tipo, valor, activo, usos_max, usos_actual, expira_en FROM marketplace_cupones WHERE codigo = :c",
        c=codigo,
    )
    if not rows:
        return CuponValidarOut(valido=False, mensaje="Cupón no válido")

    tipo, valor, activo, usos_max, usos_actual, expira_en = rows[0]
    if not activo:
        return CuponValidarOut(valido=False, mensaje="Cupón inactivo")
    if expira_en and expira_en < date.today():
        return CuponValidarOut(valido=False, mensaje="Cupón expirado")
    if usos_max is not None and usos_actual >= usos_max:
        return CuponValidarOut(valido=False, mensaje="Cupón agotado")

    valor = float(valor)
    descuento = round(subtotal * valor / 100, 2) if tipo == "porcentaje" else min(valor, subtotal)
    return CuponValidarOut(valido=True, mensaje="Cupón aplicado", tipo=tipo, valor=valor, descuento=descuento)


@router.post("/cupones/validar", response_model=CuponValidarOut)
def validar_cupon(payload: CuponValidarIn, current_user: UserOut = Depends(get_current_user)):
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return CuponValidarOut(valido=False, mensaje="No se pudo validar el cupón en este momento")
    try:
        return _validar_cupon(sconn, payload.codigo, payload.subtotal)
    finally:
        sconn.close()


def _get_pedido_items(conn, pedido_id: int) -> list[PedidoItemOut]:
    rows = conn.run(
        f"SELECT {', '.join(PEDIDO_ITEM_COLUMNS)} FROM marketplace_pedido_items WHERE pedido_id = :id ORDER BY id",
        id=pedido_id,
    )
    return [
        PedidoItemOut(
            id=r[0], producto_id=r[1], nombre=r[2], categoria=r[3],
            precio_unitario=float(r[4]), cantidad=float(r[5]), subtotal=float(r[6]),
        )
        for r in rows
    ]


def _row_to_pedido(conn, row: dict) -> PedidoOut:
    return PedidoOut(
        id=row["id"], tienda_id=row["tienda_id"], tienda_nombre=row["tienda_nombre"],
        subtotal=float(row["subtotal"]), descuento=float(row["descuento"]), total=float(row["total"]),
        cupon_codigo=row["cupon_codigo"], estado=row["estado"], wompi_reference=row["wompi_reference"],
        wompi_transaction_id=row["wompi_transaction_id"], created_at=row["created_at"],
        items=_get_pedido_items(conn, row["id"]),
    )


def _get_pedido_or_404(conn, usuario_id: int, pedido_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(PEDIDO_COLUMNS)} FROM marketplace_pedidos WHERE id = :id AND usuario_id = :uid",
        id=pedido_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return dict(zip(PEDIDO_COLUMNS, rows[0]))


def _sync_con_wompi(conn, pedido: dict) -> dict:
    """If the order is still pending and we have a Wompi transaction id
    attached, ask Wompi directly for its current status. This is a fallback
    that works even when the webhook can't reach us (e.g. local dev without
    a public tunnel) — never trust the frontend's own claim of payment."""
    if pedido["estado"] != "pendiente_pago" or not pedido["wompi_transaction_id"]:
        return pedido

    data = wompi.get_transaction(pedido["wompi_transaction_id"])
    if not data:
        return pedido

    nuevo_estado = wompi.STATUS_MAP.get(data.get("status"), "pendiente_pago")
    if nuevo_estado != pedido["estado"]:
        conn.run(
            "UPDATE marketplace_pedidos SET estado = :e, updated_at = now() WHERE id = :id",
            e=nuevo_estado, id=pedido["id"],
        )
        pedido["estado"] = nuevo_estado
    return pedido


@router.post("/pedidos", response_model=PedidoConCheckoutOut, status_code=status.HTTP_201_CREATED)
def crear_pedido(payload: PedidoIn, current_user: UserOut = Depends(get_current_user)):
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El carrito está vacío")

    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="El catálogo global no está disponible")

    try:
        tienda_rows = sconn.run(
            "SELECT nombre FROM tiendas WHERE id = :id AND activo = true", id=payload.tienda_id
        )
        if not tienda_rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada")
        tienda_nombre = tienda_rows[0][0]

        items_validos = []
        for item in payload.items:
            prod = sconn.run(
                "SELECT nombre, categoria, precio FROM marketplace_productos "
                "WHERE id = :id AND tienda_id = :tid AND activo = true",
                id=item.producto_id, tid=payload.tienda_id,
            )
            if not prod:
                continue
            nombre, categoria, precio = prod[0][0], prod[0][1], float(prod[0][2])
            items_validos.append((item.producto_id, nombre, categoria, item.cantidad, precio))

        if not items_validos:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ninguno de los productos es válido")

        subtotal = round(sum(cant * precio for _, _, _, cant, precio in items_validos), 2)

        descuento = 0.0
        cupon_codigo = None
        if payload.cupon_codigo:
            resultado = _validar_cupon(sconn, payload.cupon_codigo, subtotal)
            if not resultado.valido:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=resultado.mensaje)
            descuento = resultado.descuento
            cupon_codigo = payload.cupon_codigo.strip().upper()

        total = round(subtotal - descuento, 2)
        if total <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El total del pedido debe ser mayor a cero")

        if cupon_codigo:
            sconn.run(
                "UPDATE marketplace_cupones SET usos_actual = usos_actual + 1 WHERE codigo = :c", c=cupon_codigo
            )
    finally:
        sconn.close()

    conn = get_connection()
    try:
        reference = f"cc-{uuid.uuid4().hex[:24]}"
        rows = conn.run(
            """
            INSERT INTO marketplace_pedidos
                (usuario_id, tienda_id, tienda_nombre, subtotal, descuento, total, cupon_codigo, wompi_reference)
            VALUES (:uid, :tid, :tnombre, :subtotal, :descuento, :total, :cupon, :ref)
            RETURNING id
            """,
            uid=current_user.tenant_id, tid=payload.tienda_id, tnombre=tienda_nombre,
            subtotal=subtotal, descuento=descuento, total=total, cupon=cupon_codigo, ref=reference,
        )
        pedido_id = rows[0][0]

        for producto_id, nombre, categoria, cantidad, precio in items_validos:
            conn.run(
                "INSERT INTO marketplace_pedido_items "
                "(pedido_id, producto_id, nombre, categoria, precio_unitario, cantidad, subtotal) "
                "VALUES (:pid, :prodid, :nombre, :categoria, :precio, :cant, :subtotal)",
                pid=pedido_id, prodid=producto_id, nombre=nombre, categoria=categoria,
                precio=precio, cant=cantidad, subtotal=round(cantidad * precio, 2),
            )

        pedido = _row_to_pedido(conn, _get_pedido_or_404(conn, current_user.tenant_id, pedido_id))

        amount_in_cents = round(total * 100)
        signature = wompi.integrity_signature(reference, amount_in_cents)
        checkout = WompiCheckoutOut(
            checkout_url=os.environ["WOMPI_CHECKOUT_URL"],
            public_key=os.environ["WOMPI_PUBLIC_KEY"],
            amount_in_cents=amount_in_cents,
            reference=reference,
            signature=signature,
            redirect_url=os.environ["WOMPI_REDIRECT_URL"],
        )
        return PedidoConCheckoutOut(pedido=pedido, wompi=checkout)
    finally:
        conn.close()


@router.get("/pedidos", response_model=list[PedidoOut])
def listar_pedidos(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(PEDIDO_COLUMNS)} FROM marketplace_pedidos WHERE usuario_id = :uid ORDER BY created_at DESC",
            uid=current_user.tenant_id,
        )
        return [_row_to_pedido(conn, dict(zip(PEDIDO_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/pedidos/{pedido_id}", response_model=PedidoOut)
def get_pedido(pedido_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        pedido = _sync_con_wompi(conn, _get_pedido_or_404(conn, current_user.tenant_id, pedido_id))
        return _row_to_pedido(conn, pedido)
    finally:
        conn.close()


@router.post("/pedidos/confirmar", response_model=PedidoOut)
def confirmar_pedido(payload: ConfirmarTransaccionIn, current_user: UserOut = Depends(get_current_user)):
    """Called by the frontend right after Wompi redirects back with
    ?id=<transaction_id>. We look the order up by the transaction's own
    reference (queried from Wompi, not trusted from the client) instead of
    requiring the browser to remember which pedido it just created — this
    also makes it work if the payment finishes on a different tab/device."""
    data = wompi.get_transaction(payload.transaction_id)
    if not data or not data.get("reference"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo consultar la transacción en Wompi")

    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(PEDIDO_COLUMNS)} FROM marketplace_pedidos "
            "WHERE usuario_id = :uid AND wompi_reference = :ref",
            uid=current_user.tenant_id, ref=data["reference"],
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
        pedido = dict(zip(PEDIDO_COLUMNS, rows[0]))

        if not pedido["wompi_transaction_id"]:
            conn.run(
                "UPDATE marketplace_pedidos SET wompi_transaction_id = :tid WHERE id = :id",
                tid=payload.transaction_id, id=pedido["id"],
            )
            pedido["wompi_transaction_id"] = payload.transaction_id

        pedido = _sync_con_wompi(conn, pedido)
        return _row_to_pedido(conn, pedido)
    finally:
        conn.close()


@router.get("/listas", response_model=list[ListaCompraOut])
def list_listas(estado: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        if estado:
            rows = conn.run(
                f"SELECT {', '.join(LISTA_COLUMNS)} FROM listas_compra "
                "WHERE usuario_id = :uid AND estado = :estado ORDER BY created_at DESC",
                uid=current_user.tenant_id, estado=estado,
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(LISTA_COLUMNS)} FROM listas_compra "
                "WHERE usuario_id = :uid ORDER BY created_at DESC",
                uid=current_user.tenant_id,
            )
        return [_row_to_lista(conn, dict(zip(LISTA_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/listas/estadisticas", response_model=ListaCompraEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*) FILTER (WHERE estado = 'pendiente'), COUNT(*) FILTER (WHERE estado = 'recibido') "
            "FROM listas_compra WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return ListaCompraEstadisticasOut(pendientes=row[0], recibidas=row[1])
    finally:
        conn.close()


@router.post("/listas", response_model=ListaCompraOut, status_code=status.HTTP_201_CREATED)
def crear_lista(payload: ListaCompraIn, current_user: UserOut = Depends(get_current_user)):
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El carrito está vacío")

    conn = get_connection()
    try:
        items_validos = []
        for item in payload.items:
            insumo = conn.run(
                "SELECT nombre, precio_unitario FROM insumos WHERE id = :id AND usuario_id = :uid",
                id=item.insumo_id, uid=current_user.tenant_id,
            )
            if not insumo:
                continue
            nombre, precio = insumo[0][0], float(insumo[0][1])
            items_validos.append((item.insumo_id, nombre, item.cantidad, precio))

        if not items_validos:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ninguno de los insumos es válido")

        total = round(sum(cant * precio for _, _, cant, precio in items_validos), 2)
        numero = _generar_numero(conn, current_user.tenant_id)

        rows = conn.run(
            "INSERT INTO listas_compra (usuario_id, numero, notas, total) "
            "VALUES (:uid, :numero, :notas, :total) RETURNING id",
            uid=current_user.tenant_id, numero=numero, notas=payload.notas.strip(), total=total,
        )
        lista_id = rows[0][0]

        for insumo_id, nombre, cantidad, precio in items_validos:
            conn.run(
                "INSERT INTO lista_compra_items (lista_id, insumo_id, nombre, cantidad, precio_unitario, subtotal) "
                "VALUES (:lid, :iid, :nombre, :cant, :precio, :subtotal)",
                lid=lista_id, iid=insumo_id, nombre=nombre, cant=cantidad, precio=precio,
                subtotal=round(cantidad * precio, 2),
            )

        return _row_to_lista(conn, _get_lista_or_404(conn, current_user.tenant_id, lista_id))
    finally:
        conn.close()


@router.get("/listas/{lista_id}", response_model=ListaCompraOut)
def get_lista(lista_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_lista(conn, _get_lista_or_404(conn, current_user.tenant_id, lista_id))
    finally:
        conn.close()


@router.post("/listas/{lista_id}/recibir", response_model=ListaCompraOut)
def recibir_lista(lista_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        lista = _get_lista_or_404(conn, current_user.tenant_id, lista_id)
        if lista["estado"] != "pendiente":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta lista ya fue procesada")

        items = _get_items(conn, lista_id)
        ingreso_items = [
            IngresoItemIn(
                insumo_id=i.insumo_id, articulo=i.nombre, cantidad=i.cantidad, precio_unitario=i.precio_unitario
            )
            for i in items
        ]
        ingreso_id = _crear_ingreso(conn, current_user.tenant_id, f"Marketplace {lista['numero']}", 0, ingreso_items)

        conn.run(
            "UPDATE listas_compra SET estado = 'recibido', ingreso_id = :iid, updated_at = now() WHERE id = :id",
            iid=ingreso_id, id=lista_id,
        )
        return _row_to_lista(conn, _get_lista_or_404(conn, current_user.tenant_id, lista_id))
    finally:
        conn.close()


@router.delete("/listas/{lista_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancelar_lista(lista_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        lista = _get_lista_or_404(conn, current_user.tenant_id, lista_id)
        if lista["estado"] != "pendiente":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Solo puedes eliminar listas pendientes"
            )
        conn.run("DELETE FROM listas_compra WHERE id = :id", id=lista_id)
    finally:
        conn.close()
