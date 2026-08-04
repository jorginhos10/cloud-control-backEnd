from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.ingresos import _crear_ingreso
from app.schemas import (
    IngresoItemIn,
    ListaCompraEstadisticasOut,
    ListaCompraIn,
    ListaCompraItemOut,
    ListaCompraOut,
    MarketplaceItemOut,
)

router = APIRouter(prefix="/marketplace", dependencies=[Depends(get_current_user)])

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


@router.get("/catalogo", response_model=list[MarketplaceItemOut])
def catalogo(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT id, nombre, categoria, unidad_medida, precio_unitario, cantidad_stock "
            "FROM insumos WHERE usuario_id = :uid AND activo = true ORDER BY nombre",
            uid=current_user.tenant_id,
        )
        return [
            MarketplaceItemOut(
                id=r[0], nombre=r[1], categoria=r[2], unidad_medida=r[3],
                precio_unitario=float(r[4]), cantidad_stock=float(r[5]),
            )
            for r in rows
        ]
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
