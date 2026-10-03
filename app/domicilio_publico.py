from fastapi import APIRouter, HTTPException, Query, Request, status

from app.database import get_connection
from app.domicilios import (
    CHAT_COLUMNS,
    _get_by_token_pedido,
    _get_domicilio_or_404,
    _row_to_domicilio,
    _validar_items,
    crear_pedido,
)
from app.schemas import (
    CatalogoItemOut,
    DomicilioChatMensajeIn,
    DomicilioChatMensajeOut,
    DomicilioCotizacionIn,
    DomicilioCotizacionOut,
    DomicilioOut,
    DomicilioPedidoIn,
    LugarDetalleOut,
    LugarSugerenciaOut,
    NegocioPublicoOut,
)
from app.lugares import autocompletar, detalle_lugar, direccion_desde_coordenadas, limitar
from app.negocios import resolver_apariencia_publica
from app.sabores import sabores_por_receta
from app.tarifas_domicilio import cotizar

router = APIRouter(prefix="/domicilio-publico")

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
    ORDER BY recetas.nombre
"""


def _resolver_usuario(conn, token: str) -> int:
    rows = conn.run("SELECT id FROM usuarios WHERE domicilios_token = :t", t=token)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no encontrado")
    return rows[0][0]


@router.get("/{token}/negocio", response_model=NegocioPublicoOut)
def negocio(token: str):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        rows = conn.run(
            "SELECT nombre, logo_url, eslogan, apariencia FROM negocios WHERE usuario_id = :uid", uid=usuario_id
        )
        if not rows:
            return NegocioPublicoOut()
        nombre, logo_url, eslogan, apariencia = rows[0]
        return NegocioPublicoOut(
            nombre=nombre, logo_url=logo_url, eslogan=eslogan, apariencia=resolver_apariencia_publica(apariencia)
        )
    finally:
        conn.close()


@router.get("/{token}/catalogo", response_model=list[CatalogoItemOut])
def catalogo(token: str):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        rows = conn.run(CATALOGO_SELECT, uid=usuario_id)
        sabores = sabores_por_receta(conn, [r[0] for r in rows])
        return [
            CatalogoItemOut(
                id=r[0], nombre=r[1], categoria=r[2], precio_venta=float(r[3]),
                disponible=int(r[4]) if r[4] is not None else None,
                imagen_url=r[5],
                sabores=sabores.get(r[0], []),
            )
            for r in rows
        ]
    finally:
        conn.close()


def _ubicacion_negocio(conn, usuario_id: int) -> tuple[float, float] | None:
    from app.tarifas_domicilio import cargar_config

    cfg = cargar_config(conn, usuario_id)
    return (cfg["lat"], cfg["lng"]) if cfg["lat"] is not None and cfg["lng"] is not None else None


@router.get("/{token}/lugares/sugerencias", response_model=list[LugarSugerenciaOut])
def sugerencias_direccion(request: Request, token: str, q: str = Query(min_length=3, max_length=120), sesion: str = Query(default="", max_length=64)):
    """Predicción de direcciones mientras el cliente escribe (Google Maps). Vacío si no hay llave configurada."""
    limitar(request, "sugerencias", 90)
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        return autocompletar(q, sesion, _ubicacion_negocio(conn, usuario_id))
    finally:
        conn.close()


@router.get("/{token}/lugares/detalle", response_model=LugarDetalleOut)
def detalle_direccion(request: Request, token: str, id: str = Query(min_length=5, max_length=300), sesion: str = Query(default="", max_length=64)):
    limitar(request, "detalle", 60)
    conn = get_connection()
    try:
        _resolver_usuario(conn, token)
    finally:
        conn.close()
    return detalle_lugar(id, sesion)


@router.get("/{token}/lugares/inversa", response_model=LugarDetalleOut)
def direccion_inversa(request: Request, token: str, lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180)):
    """Dirección y barrio del punto donde está el cliente, para rellenar el formulario."""
    limitar(request, "inversa", 30)
    conn = get_connection()
    try:
        _resolver_usuario(conn, token)
    finally:
        conn.close()
    return direccion_desde_coordenadas(lat, lng)


def _valor_domicilio(conn, usuario_id: int, payload: DomicilioPedidoIn) -> float | None:
    """El valor lo calcula el servidor con la configuración del negocio; nunca se confía en lo que envía el cliente."""
    cot = cotizar(conn, usuario_id, payload.tipo, payload.direccion, payload.barrio, payload.lat, payload.lng)
    if cot.fuera_de_cobertura:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=cot.mensaje)
    return cot.valor


@router.post("/{token}/cotizar", response_model=DomicilioCotizacionOut)
def cotizar_domicilio(token: str, payload: DomicilioCotizacionIn):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        return cotizar(conn, usuario_id, "domicilio", payload.direccion, payload.barrio, payload.lat, payload.lng)
    finally:
        conn.close()


@router.post("/{token}/pedido", response_model=DomicilioOut, status_code=status.HTTP_201_CREATED)
def hacer_pedido(token: str, payload: DomicilioPedidoIn):
    if "metodo_pago" not in payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Elige cómo vas a pagar")
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        domicilio_id = crear_pedido(conn, usuario_id, payload, valor_domicilio=_valor_domicilio(conn, usuario_id, payload))
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, usuario_id, domicilio_id))
    finally:
        conn.close()


@router.get("/{token}/pedido/{token_pedido}", response_model=DomicilioOut)
def estado_pedido(token: str, token_pedido: str):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        dom = _get_by_token_pedido(conn, usuario_id, token_pedido)
        return _row_to_domicilio(conn, dom)
    finally:
        conn.close()


@router.get("/{token}/pedido/{token_pedido}/chat", response_model=list[DomicilioChatMensajeOut])
def chat_cliente_mensajes(token: str, token_pedido: str):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        dom = _get_by_token_pedido(conn, usuario_id, token_pedido)
        conn.run("UPDATE domicilio_chat SET leido = true WHERE domicilio_id = :id AND de = 'admin'", id=dom["id"])
        rows = conn.run(
            f"SELECT {', '.join(CHAT_COLUMNS)} FROM domicilio_chat WHERE domicilio_id = :id ORDER BY created_at",
            id=dom["id"],
        )
        return [DomicilioChatMensajeOut(id=r[0], de=r[1], mensaje=r[2], leido=r[3], created_at=r[4]) for r in rows]
    finally:
        conn.close()


@router.post(
    "/{token}/pedido/{token_pedido}/chat",
    response_model=DomicilioChatMensajeOut,
    status_code=status.HTTP_201_CREATED,
)
def chat_cliente_enviar(token: str, token_pedido: str, payload: DomicilioChatMensajeIn):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        dom = _get_by_token_pedido(conn, usuario_id, token_pedido)
        rows = conn.run(
            f"INSERT INTO domicilio_chat (domicilio_id, de, mensaje) VALUES (:id, 'cliente', :msg) "
            f"RETURNING {', '.join(CHAT_COLUMNS)}",
            id=dom["id"], msg=payload.mensaje.strip(),
        )
        r = rows[0]
        return DomicilioChatMensajeOut(id=r[0], de=r[1], mensaje=r[2], leido=r[3], created_at=r[4])
    finally:
        conn.close()


@router.post("/{token}/pedido/{token_pedido}/cancelar", response_model=DomicilioOut)
def cancelar_pedido(token: str, token_pedido: str):
    """El cliente cancela su pedido, solo mientras el negocio no lo haya aceptado (estado pendiente)."""
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        dom = _get_by_token_pedido(conn, usuario_id, token_pedido)
        # La condición de estado va en el UPDATE para que no se cancele un pedido que el negocio
        # aceptó justo en ese momento.
        rows = conn.run(
            "UPDATE domicilios SET estado = 'cancelado', updated_at = now() "
            "WHERE id = :id AND estado = 'pendiente' RETURNING id",
            id=dom["id"],
        )
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tu pedido ya fue aceptado por el negocio y no se puede cancelar.",
            )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, usuario_id, dom["id"]))
    finally:
        conn.close()


@router.put("/{token}/pedido/{token_pedido}", response_model=DomicilioOut)
def modificar_pedido(token: str, token_pedido: str, payload: DomicilioPedidoIn):
    """El cliente cambia ítems, datos de entrega o notas, solo mientras el pedido sigue pendiente."""
    if "metodo_pago" not in payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Elige cómo vas a pagar")
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        dom = _get_by_token_pedido(conn, usuario_id, token_pedido)

        if not payload.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El pedido no tiene ítems")
        items = _validar_items(conn, usuario_id, payload.items)
        if not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ninguno de los ítems es válido")
        total = round(sum(i["precio"] * i["cantidad"] for i in items), 2)
        valor_domicilio = _valor_domicilio(conn, usuario_id, payload)

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
                detail="Tu pedido ya fue aceptado por el negocio y no se puede modificar.",
            )

        conn.run("DELETE FROM domicilio_items WHERE domicilio_id = :id", id=dom["id"])
        for item in items:
            conn.run(
                "INSERT INTO domicilio_items (domicilio_id, receta_id, nombre, precio, cantidad) "
                "VALUES (:did, :rid, :nombre, :precio, :cant)",
                did=dom["id"], rid=item["receta_id"], nombre=item["nombre"], precio=item["precio"],
                cant=item["cantidad"],
            )
        # Aviso en el chat del pedido para que el negocio note el cambio antes de aceptarlo.
        conn.run(
            "INSERT INTO domicilio_chat (domicilio_id, de, mensaje) VALUES (:id, 'cliente', :msg)",
            id=dom["id"], msg="El cliente modificó su pedido.",
        )
        return _row_to_domicilio(conn, _get_domicilio_or_404(conn, usuario_id, dom["id"]))
    finally:
        conn.close()
