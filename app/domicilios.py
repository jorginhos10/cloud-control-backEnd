import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    DomicilioChatMensajeIn,
    DomicilioChatMensajeOut,
    DomicilioChatResumenOut,
    DomicilioEstadisticasOut,
    DomicilioEstadoIn,
    DomicilioInternoIn,
    DomicilioItemOut,
    DomicilioOut,
    DomicilioPedidoIn,
    DomicilioTokenOut,
)

router = APIRouter(prefix="/domicilios", dependencies=[Depends(get_current_user)])

DOMICILIO_COLUMNS = [
    "id", "token_pedido", "nombre_cliente", "telefono", "direccion", "barrio", "notas",
    "tipo", "estado", "total", "valor_domicilio", "created_at", "updated_at",
]
ITEM_COLUMNS = ["id", "receta_id", "nombre", "precio", "cantidad"]
CHAT_COLUMNS = ["id", "de", "mensaje", "leido", "created_at"]


def _get_items(conn, domicilio_id: int) -> list[DomicilioItemOut]:
    rows = conn.run(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM domicilio_items WHERE domicilio_id = :id ORDER BY id",
        id=domicilio_id,
    )
    return [
        DomicilioItemOut(id=r[0], receta_id=r[1], nombre=r[2], precio=float(r[3]), cantidad=r[4]) for r in rows
    ]


def _row_to_domicilio(conn, row: dict) -> DomicilioOut:
    return DomicilioOut(
        id=row["id"], token_pedido=row["token_pedido"], nombre_cliente=row["nombre_cliente"],
        telefono=row["telefono"] or "", direccion=row["direccion"] or "", barrio=row["barrio"] or "",
        notas=row["notas"] or "", tipo=row["tipo"], estado=row["estado"], total=float(row["total"]),
        valor_domicilio=float(row["valor_domicilio"]) if row["valor_domicilio"] is not None else None,
        created_at=row["created_at"], updated_at=row["updated_at"], items=_get_items(conn, row["id"]),
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
        resultado.append({"receta_id": item.receta_id, "nombre": nombre, "precio": precio, "cantidad": item.cantidad})
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
        "(usuario_id, token_pedido, nombre_cliente, telefono, direccion, barrio, notas, tipo, total, valor_domicilio) "
        "VALUES (:uid, :token, :nombre, :tel, :dir, :barrio, :notas, :tipo, :total, :vd) RETURNING id",
        uid=usuario_id, token=token_pedido, nombre=payload.nombre_cliente.strip(), tel=payload.telefono.strip(),
        dir=payload.direccion.strip(), barrio=payload.barrio.strip(), notas=payload.notas.strip(),
        tipo=payload.tipo, total=total, vd=valor_domicilio,
    )
    domicilio_id = rows[0][0]

    for item in items:
        conn.run(
            "INSERT INTO domicilio_items (domicilio_id, receta_id, nombre, precio, cantidad) "
            "VALUES (:did, :rid, :nombre, :precio, :cant)",
            did=domicilio_id, rid=item["receta_id"], nombre=item["nombre"], precio=item["precio"],
            cant=item["cantidad"],
        )

    return domicilio_id


def _validar_transicion(estado_actual: str, tipo: str, estado_nuevo: str) -> None:
    permitidas = {
        "pendiente": {"preparacion", "cancelado"},
        "preparacion": {"listo"},
        "listo": {"en_camino"} if tipo == "domicilio" else {"entregado"},
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
        return [_row_to_domicilio(conn, dict(zip(DOMICILIO_COLUMNS, r))) for r in rows]
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


@router.patch("/{domicilio_id}/estado", response_model=DomicilioOut)
def cambiar_estado(domicilio_id: int, payload: DomicilioEstadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        dom = _get_domicilio_or_404(conn, current_user.tenant_id, domicilio_id)
        _validar_transicion(dom["estado"], dom["tipo"], payload.estado)

        valor_domicilio = float(dom["valor_domicilio"]) if dom["valor_domicilio"] is not None else None
        if payload.estado == "preparacion" and dom["tipo"] == "domicilio":
            if payload.valor_domicilio is not None:
                valor_domicilio = payload.valor_domicilio
            if valor_domicilio is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Debes indicar el valor del domicilio"
                )

        conn.run(
            "UPDATE domicilios SET estado = :e, valor_domicilio = :vd, updated_at = now() WHERE id = :id",
            e=payload.estado, vd=valor_domicilio, id=domicilio_id,
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
