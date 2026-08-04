from fastapi import APIRouter, HTTPException, status

from app.database import get_connection
from app.domicilios import (
    CHAT_COLUMNS,
    _get_by_token_pedido,
    _get_domicilio_or_404,
    _row_to_domicilio,
    crear_pedido,
)
from app.schemas import (
    CatalogoItemOut,
    DomicilioChatMensajeIn,
    DomicilioChatMensajeOut,
    DomicilioOut,
    DomicilioPedidoIn,
)

router = APIRouter(prefix="/domicilio-publico")

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
    ORDER BY recetas.nombre
"""


def _resolver_usuario(conn, token: str) -> int:
    rows = conn.run("SELECT id FROM usuarios WHERE domicilios_token = :t", t=token)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no encontrado")
    return rows[0][0]


@router.get("/{token}/catalogo", response_model=list[CatalogoItemOut])
def catalogo(token: str):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        rows = conn.run(CATALOGO_SELECT, uid=usuario_id)
        return [
            CatalogoItemOut(
                id=r[0], nombre=r[1], categoria=r[2], precio_venta=float(r[3]),
                disponible=int(r[4]) if r[4] is not None else None,
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.post("/{token}/pedido", response_model=DomicilioOut, status_code=status.HTTP_201_CREATED)
def hacer_pedido(token: str, payload: DomicilioPedidoIn):
    conn = get_connection()
    try:
        usuario_id = _resolver_usuario(conn, token)
        domicilio_id = crear_pedido(conn, usuario_id, payload)
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
