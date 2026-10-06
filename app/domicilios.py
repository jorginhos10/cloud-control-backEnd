import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    DomicilioChatMensajeIn,
    DomicilioChatMensajeOut,
    DomicilioChatResumenOut,
    DomicilioConfigIn,
    DomicilioEstadisticasOut,
    DomicilioEstadoIn,
    DomicilioInternoIn,
    DomicilioItemOut,
    DomicilioOut,
    DomicilioPedidoIn,
    DomicilioTokenOut,
    DomicilioUbicacionOut,
)
from app.tarifas_domicilio import cargar_config, geocodificar

router = APIRouter(prefix="/domicilios", dependencies=[Depends(get_current_user)])

DOMICILIO_COLUMNS = [
    "id", "token_pedido", "nombre_cliente", "telefono", "direccion", "barrio", "notas",
    "tipo", "estado", "total", "valor_domicilio", "created_at", "updated_at", "metodo_pago",
    "motivo_cancelacion", "repartidor_id",
]
ITEM_COLUMNS = [
    "id", "receta_id", "nombre", "precio", "cantidad", "sabor_id", "sabor_nombre", "topping_id", "topping_nombre",
]
CHAT_COLUMNS = ["id", "de", "mensaje", "leido", "created_at"]


def _get_items(conn, domicilio_id: int) -> list[DomicilioItemOut]:
    rows = conn.run(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM domicilio_items WHERE domicilio_id = :id ORDER BY id",
        id=domicilio_id,
    )
    return [
        DomicilioItemOut(
            id=r[0], receta_id=r[1], nombre=r[2], precio=float(r[3]), cantidad=r[4], sabor_id=r[5], sabor_nombre=r[6],
            topping_id=r[7], topping_nombre=r[8],
        )
        for r in rows
    ]


def _get_items_por_domicilios(conn, domicilio_ids: list[int]) -> dict[int, list[DomicilioItemOut]]:
    """Trae los items de varios pedidos en una sola consulta, agrupados por domicilio_id.
    Evita pedir los items pedido por pedido (N+1) al armar un listado completo."""
    agrupado: dict[int, list[DomicilioItemOut]] = {did: [] for did in domicilio_ids}
    if not domicilio_ids:
        return agrupado
    rows = conn.run(
        f"SELECT domicilio_id, {', '.join(ITEM_COLUMNS)} FROM domicilio_items "
        "WHERE domicilio_id = ANY(:ids) ORDER BY domicilio_id, id",
        ids=domicilio_ids,
    )
    for r in rows:
        agrupado[r[0]].append(
            DomicilioItemOut(
                id=r[1], receta_id=r[2], nombre=r[3], precio=float(r[4]), cantidad=r[5],
                sabor_id=r[6], sabor_nombre=r[7], topping_id=r[8], topping_nombre=r[9],
            )
        )
    return agrupado


def _row_to_domicilio(conn, row: dict, items: list[DomicilioItemOut] | None = None) -> DomicilioOut:
    return DomicilioOut(
        id=row["id"], token_pedido=row["token_pedido"], nombre_cliente=row["nombre_cliente"],
        telefono=row["telefono"] or "", direccion=row["direccion"] or "", barrio=row["barrio"] or "",
        notas=row["notas"] or "", tipo=row["tipo"], metodo_pago=row["metodo_pago"] or "", estado=row["estado"], total=float(row["total"]),
        valor_domicilio=float(row["valor_domicilio"]) if row["valor_domicilio"] is not None else None,
        created_at=row["created_at"], updated_at=row["updated_at"], motivo_cancelacion=row["motivo_cancelacion"] or "",
        repartidor_id=row["repartidor_id"],
        items=items if items is not None else _get_items(conn, row["id"]),
    )


def _get_domicilio_or_404(conn, usuario_id: int, domicilio_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(DOMICILIO_COLUMNS)} FROM domicilios WHERE id = :id AND usuario_id = :uid",
        id=domicilio_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return dict(zip(DOMICILIO_COLUMNS, rows[0]))


def _get_by_token_pedido(conn, usuario_id: int, token_pedido: str) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(DOMICILIO_COLUMNS)} FROM domicilios WHERE token_pedido = :tp AND usuario_id = :uid",
        tp=token_pedido, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return dict(zip(DOMICILIO_COLUMNS, rows[0]))


def _validar_items(conn, usuario_id: int, items_in) -> list[dict]:
    resultado = []
    for item in items_in:
        receta = conn.run(
            "SELECT nombre, precio_venta FROM recetas WHERE id = :id AND usuario_id = :uid AND activo = true",
            id=item.receta_id, uid=usuario_id,
        )
        if not receta:
            continue
        nombre, precio = receta[0][0], float(receta[0][1])

        sabor_id = getattr(item, "sabor_id", None)
        sabor_nombre = None
        if sabor_id is not None:
            sabor = conn.run(
                "SELECT s.nombre FROM receta_sabores rs JOIN sabores s ON s.id = rs.id_sabor "
                "WHERE rs.id_receta = :rid AND s.id = :sid",
                rid=item.receta_id, sid=sabor_id,
            )
            if not sabor:
                continue
            sabor_nombre = sabor[0][0]

        topping_id = getattr(item, "topping_id", None)
        topping_nombre = None
        if topping_id is not None:
            topping = conn.run(
                "SELECT t.nombre, rt.precio_adicional FROM receta_toppings rt JOIN toppings t ON t.id = rt.id_topping "
                "WHERE rt.id_receta = :rid AND t.id = :tid",
                rid=item.receta_id, tid=topping_id,
            )
            if not topping:
                continue
            topping_nombre = topping[0][0]
            precio += float(topping[0][1])

        resultado.append({
            "receta_id": item.receta_id, "nombre": nombre, "precio": precio, "cantidad": item.cantidad,
            "sabor_id": sabor_id, "sabor_nombre": sabor_nombre,
            "topping_id": topping_id, "topping_nombre": topping_nombre,
        })
    return resultado


def crear_pedido(conn, usuario_id: int, payload: DomicilioPedidoIn, valor_domicilio: float | None = None) -> int:
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El pedido no tiene ítems")

    items = _validar_items(conn, usuario_id, payload.items)
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ninguno de los ítems es válido")

    total = round(sum(i["precio"] * i["cantidad"] for i in items), 2)
    token_pedido = secrets.token_hex(16)

    rows = conn.run(
        "INSERT INTO domicilios "
        "(usuario_id, token_pedido, nombre_cliente, telefono, direccion, barrio, notas, tipo, total, valor_domicilio, metodo_pago) "
        "VALUES (:uid, :token, :nombre, :tel, :dir, :barrio, :notas, :tipo, :total, :vd, :mp) RETURNING id",
        uid=usuario_id, token=token_pedido, nombre=payload.nombre_cliente.strip(), tel=payload.telefono.strip(),
        dir=payload.direccion.strip(), barrio=payload.barrio.strip(), notas=payload.notas.strip(),
        tipo=payload.tipo, total=total, vd=valor_domicilio, mp=payload.metodo_pago,
    )
    domicilio_id = rows[0][0]

    for item in items:
        conn.run(
            "INSERT INTO domicilio_items (domicilio_id, receta_id, nombre, precio, cantidad, sabor_id, sabor_nombre, "
            "topping_id, topping_nombre) "
            "VALUES (:did, :rid, :nombre, :precio, :cant, :sid, :sabor_nombre, :tid, :topping_nombre)",
            did=domicilio_id, rid=item["receta_id"], nombre=item["nombre"], precio=item["precio"],
            cant=item["cantidad"], sid=item["sabor_id"], sabor_nombre=item["sabor_nombre"],
            tid=item["topping_id"], topping_nombre=item["topping_nombre"],
        )

    return domicilio_id


def _validar_transicion(estado_actual: str, tipo: str, estado_nuevo: str) -> None:
    permitidas = {
        "pendiente": {"preparacion", "cancelado"},
        "preparacion": {"listo", "cancelado"},
        "listo": ({"en_camino"} if tipo == "domicilio" else {"entregado"}) | {"cancelado"},
        "en_camino": {"entregado"},
    }.get(estado_actual, set())
    if estado_nuevo not in permitidas:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transición de estado inválida")


@router.get("", response_model=list[DomicilioOut])
def list_domicilios(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(DOMICILIO_COLUMNS)} FROM domicilios "
            "WHERE usuario_id = :uid AND estado NOT IN ('entregado', 'cancelado') "
            "ORDER BY created_at ASC",
            uid=current_user.tenant_id,
        )
        dicts = [dict(zip(DOMICILIO_COLUMNS, r)) for r in rows]
        items_por_domicilio = _get_items_por_domicilios(conn, [d["id"] for d in dicts])
        return [_row_to_domicilio(conn, d, items_por_domicilio[d["id"]]) for d in dicts]
    finally:
        conn.close()


@router.get("/disponibles", response_model=list[DomicilioOut])
def pedidos_disponibles(current_user: UserOut = Depends(get_current_user)):
    """Pedidos sin reclamar que la app de domiciliarios puede mostrar: los "listo" (ya se pueden
    tomar) y los "preparacion" (el negocio ya los aprobó, el repartidor los ve venir pero todavía
    no los puede reclamar — eso lo sigue exigiendo /reclamar). Los "recoger" no entran aquí: no
    necesitan repartidor."""
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(DOMICILIO_COLUMNS)} FROM domicilios "
            "WHERE usuario_id = :uid AND tipo = 'domicilio' AND estado IN ('listo', 'preparacion') "
            "AND repartidor_id IS NULL "
            "ORDER BY (estado = 'listo') DESC, created_at ASC",
            uid=current_user.tenant_id,
        )
        dicts = [dict(zip(DOMICILIO_COLUMNS, r)) for r in rows]
        items_por_domicilio = _get_items_por_domicilios(conn, [d["id"] for d in dicts])
        return [_row_to_domicilio(conn, d, items_por_domicilio[d["id"]]) for d in dicts]
    finally:
        conn.close()


@router.get("/mis-pedidos", response_model=list[DomicilioOut])
def mis_pedidos(current_user: UserOut = Depends(get_current_user)):
    """Pedidos reclamados por el repartidor actual: los activos (listo/en_camino) más los que
    ya entregó hoy, para que su lista del día no desaparezca apenas marca "entregado"."""
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(DOMICILIO_COLUMNS)} FROM domicilios "
            "WHERE usuario_id = :uid AND repartidor_id = :rid "
            "AND (estado IN ('listo', 'en_camino') OR (estado = 'entregado' AND updated_at::date = CURRENT_DATE)) "
            "ORDER BY created_at ASC",
            uid=current_user.tenant_id, rid=current_user.id,
        )
        dicts = [dict(zip(DOMICILIO_COLUMNS, r)) for r in rows]
        items_por_domicilio = _get_items_por_domicilios(conn, [d["id"] for d in dicts])
        return [_row_to_domicilio(conn, d, items_por_domicilio[d["id"]]) for d in dicts]
    finally:
        conn.close()


@router.post("/{domicilio_id}/reclamar", response_model=DomicilioOut)
def reclamar_pedido(domicilio_id: int, current_user: UserOut = Depends(get_current_user)):
    """El repartidor toma un pedido disponible. Usa una condición atómica (repartidor_id IS NULL)
    para que, si dos repartidores lo tocan al mismo tiempo, solo el primero lo gane."""
    conn = get_connection()
    try:
        rows = conn.run(
            "UPDATE domicilios SET repartidor_id = :rid, updated_at = now() "
            "WHERE id = :id AND usuario_id = :uid AND tipo = 'domicilio' AND estado = 'listo' "
            "AND repartidor_id IS NULL "
            "RETURNING id",
            rid=current_user.id, id=domicilio_id, uid=current_user.tenant_id,
        )
        if not rows:
            existe = conn.run(
                "SELECT id FROM domicilios WHERE id = :id AND usuario_id = :uid",
                id=domicilio_id, uid=current_user.tenant_id,
            )
            if not existe:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Este pedido ya fue tomado por otro repartidor"
            )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id))
    finally:
        conn.close()


@router.get("/estadisticas", response_model=DomicilioEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*) FILTER (WHERE estado NOT IN ('entregado', 'cancelado')), "
            "COUNT(*) FILTER (WHERE estado = 'pendiente') "
            "FROM domicilios WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return DomicilioEstadisticasOut(activos=row[0], pendientes=row[1])
    finally:
        conn.close()


@router.get("/token", response_model=DomicilioTokenOut)
def get_token(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run("SELECT domicilios_token FROM usuarios WHERE id = :id", id=current_user.tenant_id)
        token = rows[0][0]
        if not token:
            token = secrets.token_hex(16)
            conn.run("UPDATE usuarios SET domicilios_token = :t WHERE id = :id", t=token, id=current_user.tenant_id)
        return DomicilioTokenOut(token=token)
    finally:
        conn.close()


@router.post("/token/regenerar", response_model=DomicilioTokenOut)
def regenerar_token(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        token = secrets.token_hex(16)
        conn.run("UPDATE usuarios SET domicilios_token = :t WHERE id = :id", t=token, id=current_user.tenant_id)
        return DomicilioTokenOut(token=token)
    finally:
        conn.close()


@router.post("/interno", response_model=DomicilioOut, status_code=status.HTTP_201_CREATED)
def crear_interno(payload: DomicilioInternoIn, current_user: UserOut = Depends(get_current_user)):
    if payload.tipo == "domicilio" and payload.valor_domicilio is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debes indicar el valor del domicilio")

    conn = get_connection()
    try:
        domicilio_id = crear_pedido(conn, current_user.tenant_id, payload, valor_domicilio=payload.valor_domicilio)
        conn.run(
            "UPDATE domicilios SET estado = 'preparacion', updated_at = now() WHERE id = :id", id=domicilio_id
        )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id))
    finally:
        conn.close()


@router.get("/config", response_model=DomicilioConfigIn)
def get_config(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return DomicilioConfigIn(**cargar_config(conn, current_user.tenant_id))
    finally:
        conn.close()


@router.put("/config", response_model=DomicilioConfigIn)
def guardar_config(payload: DomicilioConfigIn, current_user: UserOut = Depends(get_current_user)):
    if payload.modo == "personalizado" and payload.valor_fijo is not None and payload.valor_fijo == 0:
        payload.valor_fijo = None
    if payload.modo == "automatico" and (payload.lat is None or payload.lng is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Para el precio automático define la ubicación de tu negocio.",
        )
    conn = get_connection()
    try:
        conn.run(
            "INSERT INTO domicilio_config (usuario_id, modo, valor_fijo, tarifa_base, km_base, valor_km, "
            "radio_max_km, lat, lng) VALUES (:uid, :modo, :vf, :tb, :kb, :vk, :rm, :lat, :lng) "
            "ON CONFLICT (usuario_id) DO UPDATE SET modo = :modo, valor_fijo = :vf, tarifa_base = :tb, "
            "km_base = :kb, valor_km = :vk, radio_max_km = :rm, lat = :lat, lng = :lng, updated_at = now()",
            uid=current_user.tenant_id, modo=payload.modo, vf=payload.valor_fijo, tb=payload.tarifa_base,
            kb=payload.km_base, vk=payload.valor_km, rm=payload.radio_max_km, lat=payload.lat, lng=payload.lng,
        )
        return DomicilioConfigIn(**cargar_config(conn, current_user.tenant_id))
    finally:
        conn.close()


@router.post("/config/ubicacion-desde-direccion", response_model=DomicilioUbicacionOut)
def ubicacion_desde_direccion(current_user: UserOut = Depends(get_current_user)):
    """Ubica el negocio a partir de la dirección y la ciudad guardadas en su perfil."""
    conn = get_connection()
    try:
        rows = conn.run("SELECT direccion, ciudad FROM negocios WHERE usuario_id = :uid", uid=current_user.tenant_id)
    finally:
        conn.close()
    direccion = (rows[0][0] or "").strip() if rows else ""
    ciudad = (rows[0][1] or "").strip() if rows else ""
    if not direccion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu negocio no tiene dirección guardada. Complétala en Configuración > Negocio o usa tu ubicación actual.",
        )
    ubicacion = geocodificar(", ".join(p for p in (direccion, ciudad) if p))
    if ubicacion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pudimos ubicar esa dirección. Usa tu ubicación actual desde el celular.",
        )
    return DomicilioUbicacionOut(lat=ubicacion[0], lng=ubicacion[1])


@router.put("/{domicilio_id}", response_model=DomicilioOut)
def modificar_pedido(domicilio_id: int, payload: DomicilioInternoIn, current_user: UserOut = Depends(get_current_user)):
    """El negocio corrige un pedido antes de aprobarlo (ítems, datos del cliente, notas, valor del domicilio)."""
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El pedido no tiene ítems")

    conn = get_connection()
    try:
        dom = _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id)
        items = _validar_items(conn, current_user.tenant_id, payload.items)
        if not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ninguno de los ítems es válido")
        total = round(sum(i["precio"] * i["cantidad"] for i in items), 2)
        valor_domicilio = payload.valor_domicilio if payload.tipo == "domicilio" else None

        rows = conn.run(
            "UPDATE domicilios SET nombre_cliente = :nombre, telefono = :tel, direccion = :dir, barrio = :barrio, "
            "notas = :notas, tipo = :tipo, total = :total, valor_domicilio = :vd, metodo_pago = :mp, updated_at = now() "
            "WHERE id = :id AND estado = 'pendiente' RETURNING id",
            id=dom["id"], nombre=payload.nombre_cliente.strip(), tel=payload.telefono.strip(),
            dir=payload.direccion.strip(), barrio=payload.barrio.strip(), notas=payload.notas.strip(),
            tipo=payload.tipo, total=total, vd=valor_domicilio, mp=payload.metodo_pago,
        )
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El pedido ya no está pendiente y no se puede modificar.",
            )

        conn.run("DELETE FROM domicilio_items WHERE domicilio_id = :id", id=dom["id"])
        for item in items:
            conn.run(
                "INSERT INTO domicilio_items (domicilio_id, receta_id, nombre, precio, cantidad, sabor_id, sabor_nombre, "
                "topping_id, topping_nombre) "
                "VALUES (:did, :rid, :nombre, :precio, :cant, :sid, :sabor_nombre, :tid, :topping_nombre)",
                did=dom["id"], rid=item["receta_id"], nombre=item["nombre"], precio=item["precio"],
                cant=item["cantidad"], sid=item["sabor_id"], sabor_nombre=item["sabor_nombre"],
                tid=item["topping_id"], topping_nombre=item["topping_nombre"],
            )
        # Aviso en el chat para que el cliente vea que el negocio ajustó su pedido.
        conn.run(
            "INSERT INTO domicilio_chat (domicilio_id, de, mensaje) VALUES (:id, 'admin', :msg)",
            id=dom["id"], msg="El negocio modificó tu pedido.",
        )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, current_user.tenant_id, dom["id"]))
    finally:
        conn.close()


@router.patch("/{domicilio_id}/estado", response_model=DomicilioOut)
def cambiar_estado(domicilio_id: int, payload: DomicilioEstadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        dom = _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id)
        # Un domiciliario solo puede mover el pedido que él mismo reclamó; el resto del staff
        # (mesero, cocina, admin) sigue sin esta restricción, como siempre.
        if current_user.rol == "domiciliario" and dom["repartidor_id"] != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este pedido no está asignado a ti")
        _validar_transicion(dom["estado"], dom["tipo"], payload.estado)

        valor_domicilio = float(dom["valor_domicilio"]) if dom["valor_domicilio"] is not None else None
        if payload.estado == "preparacion" and dom["tipo"] == "domicilio":
            if payload.valor_domicilio is not None:
                valor_domicilio = payload.valor_domicilio
            if valor_domicilio is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Debes indicar el valor del domicilio"
                )

        motivo_cancelacion = dom["motivo_cancelacion"] or ""
        # Un pedido "pendiente" aún no lo había visto el cliente como aceptado, así que rechazarlo
        # no necesita explicación; cancelar uno ya en preparación o listo sí, porque el cliente lo
        # está esperando.
        if payload.estado == "cancelado" and dom["estado"] in ("preparacion", "listo"):
            motivo = (payload.motivo or "").strip()
            if not motivo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Escribe el motivo de la cancelación"
                )
            motivo_cancelacion = motivo

        conn.run(
            "UPDATE domicilios SET estado = :e, valor_domicilio = :vd, motivo_cancelacion = :mc, updated_at = now() "
            "WHERE id = :id",
            e=payload.estado, vd=valor_domicilio, mc=motivo_cancelacion, id=domicilio_id,
        )
        if payload.estado == "cancelado" and motivo_cancelacion:
            conn.run(
                "INSERT INTO domicilio_chat (domicilio_id, de, mensaje) VALUES (:id, 'admin', :msg)",
                id=domicilio_id, msg=f"Pedido cancelado: {motivo_cancelacion}",
            )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id))
    finally:
        conn.close()


@router.get("/chat-resumen", response_model=list[DomicilioChatResumenOut])
def chat_resumen(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT d.id, d.nombre_cliente, d.tipo, d.estado, "
            "lm.mensaje, lm.de, lm.created_at, COALESCE(nl.cnt, 0) "
            "FROM domicilios d "
            "LEFT JOIN LATERAL ("
            "    SELECT mensaje, de, created_at FROM domicilio_chat "
            "    WHERE domicilio_id = d.id ORDER BY created_at DESC LIMIT 1"
            ") lm ON true "
            "LEFT JOIN ("
            "    SELECT domicilio_id, COUNT(*) AS cnt FROM domicilio_chat "
            "    WHERE de = 'cliente' AND leido = false GROUP BY domicilio_id"
            ") nl ON nl.domicilio_id = d.id "
            "WHERE d.usuario_id = :uid AND d.estado NOT IN ('entregado', 'cancelado') "
            "ORDER BY COALESCE(lm.created_at, d.created_at) DESC",
            uid=current_user.tenant_id,
        )
        return [
            DomicilioChatResumenOut(
                domicilio_id=r[0], nombre_cliente=r[1], tipo=r[2], estado=r[3],
                ultimo_mensaje=r[4], ultimo_mensaje_de=r[5], ultimo_mensaje_at=r[6], no_leidos=r[7],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{domicilio_id}/chat", response_model=list[DomicilioChatMensajeOut])
def chat_mensajes(domicilio_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id)
        conn.run(
            "UPDATE domicilio_chat SET leido = true WHERE domicilio_id = :id AND de = 'cliente'", id=domicilio_id
        )
        rows = conn.run(
            f"SELECT {', '.join(CHAT_COLUMNS)} FROM domicilio_chat WHERE domicilio_id = :id ORDER BY created_at",
            id=domicilio_id,
        )
        return [DomicilioChatMensajeOut(id=r[0], de=r[1], mensaje=r[2], leido=r[3], created_at=r[4]) for r in rows]
    finally:
        conn.close()


@router.post("/{domicilio_id}/chat", response_model=DomicilioChatMensajeOut, status_code=status.HTTP_201_CREATED)
def chat_enviar(
    domicilio_id: int, payload: DomicilioChatMensajeIn, current_user: UserOut = Depends(get_current_user)
):
    conn = get_connection()
    try:
        _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id)
        rows = conn.run(
            f"INSERT INTO domicilio_chat (domicilio_id, de, mensaje) VALUES (:id, 'admin', :msg) "
            f"RETURNING {', '.join(CHAT_COLUMNS)}",
            id=domicilio_id, msg=payload.mensaje.strip(),
        )
        r = rows[0]
        return DomicilioChatMensajeOut(id=r[0], de=r[1], mensaje=r[2], leido=r[3], created_at=r[4])
    finally:
        conn.close()
