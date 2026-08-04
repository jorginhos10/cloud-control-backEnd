from fastapi import APIRouter, Depends, HTTPException, Query, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import InsumoActivoIn, InsumoEstadisticasOut, InsumoIn, InsumoOut

router = APIRouter(prefix="/insumos", dependencies=[Depends(get_current_user)])

FOREIGN_KEY_VIOLATION = "23503"

INSUMO_COLUMNS = [
    "id", "nombre", "descripcion", "categoria", "unidad_medida",
    "cantidad_stock", "cantidad_minima", "precio_unitario", "activo", "created_at",
]


def _stock_estado(stock: float, minimo: float) -> str:
    if stock <= 0:
        return "critico"
    if stock <= minimo:
        return "bajo"
    return "ok"


def _row_to_insumo(row: dict) -> InsumoOut:
    return InsumoOut(
        id=row["id"],
        nombre=row["nombre"],
        descripcion=row["descripcion"],
        categoria=row["categoria"],
        unidad_medida=row["unidad_medida"],
        cantidad_stock=float(row["cantidad_stock"]),
        cantidad_minima=float(row["cantidad_minima"]),
        precio_unitario=float(row["precio_unitario"]),
        activo=row["activo"],
        created_at=row["created_at"],
        stock_estado=_stock_estado(float(row["cantidad_stock"]), float(row["cantidad_minima"])),
    )


@router.get("", response_model=list[InsumoOut])
def list_insumos(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                f"SELECT {', '.join(INSUMO_COLUMNS)} FROM insumos "
                "WHERE usuario_id = :uid AND (nombre ILIKE :q OR categoria ILIKE :q OR descripcion ILIKE :q) "
                "ORDER BY nombre",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(INSUMO_COLUMNS)} FROM insumos WHERE usuario_id = :uid ORDER BY nombre",
                uid=current_user.tenant_id,
            )
        return [_row_to_insumo(dict(zip(INSUMO_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=InsumoEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE activo), "
            "COUNT(*) FILTER (WHERE activo AND cantidad_stock <= cantidad_minima), "
            "COUNT(DISTINCT categoria) "
            "FROM insumos WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return InsumoEstadisticasOut(total=row[0], activos=row[1], stock_bajo=row[2], categorias=row[3])
    finally:
        conn.close()


def _get_insumo_or_404(conn, usuario_id: int, insumo_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(INSUMO_COLUMNS)} FROM insumos WHERE id = :id AND usuario_id = :uid",
        id=insumo_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")
    return dict(zip(INSUMO_COLUMNS, rows[0]))


@router.get("/{insumo_id}", response_model=InsumoOut)
def get_insumo(insumo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_insumo(_get_insumo_or_404(conn, current_user.tenant_id, insumo_id))
    finally:
        conn.close()


@router.post("", response_model=InsumoOut, status_code=status.HTTP_201_CREATED)
def create_insumo(payload: InsumoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO insumos (usuario_id, nombre, descripcion, categoria, unidad_medida, cantidad_stock, "
            "cantidad_minima, precio_unitario, activo) "
            "VALUES (:uid, :nombre, :descripcion, :categoria, :unidad, :stock, :minima, :precio, :activo) "
            f"RETURNING {', '.join(INSUMO_COLUMNS)}",
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria=payload.categoria,
            unidad=payload.unidad_medida,
            stock=payload.cantidad_stock,
            minima=payload.cantidad_minima,
            precio=payload.precio_unitario,
            activo=payload.activo,
        )
        return _row_to_insumo(dict(zip(INSUMO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{insumo_id}", response_model=InsumoOut)
def update_insumo(insumo_id: int, payload: InsumoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_insumo_or_404(conn, current_user.tenant_id, insumo_id)
        rows = conn.run(
            "UPDATE insumos SET nombre = :nombre, descripcion = :descripcion, categoria = :categoria, "
            "unidad_medida = :unidad, cantidad_stock = :stock, cantidad_minima = :minima, "
            "precio_unitario = :precio, activo = :activo "
            f"WHERE id = :id AND usuario_id = :uid RETURNING {', '.join(INSUMO_COLUMNS)}",
            id=insumo_id,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria=payload.categoria,
            unidad=payload.unidad_medida,
            stock=payload.cantidad_stock,
            minima=payload.cantidad_minima,
            precio=payload.precio_unitario,
            activo=payload.activo,
        )
        return _row_to_insumo(dict(zip(INSUMO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{insumo_id}/activo", response_model=InsumoOut)
def toggle_activo(insumo_id: int, payload: InsumoActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_insumo_or_404(conn, current_user.tenant_id, insumo_id)
        rows = conn.run(
            f"UPDATE insumos SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(INSUMO_COLUMNS)}",
            id=insumo_id,
            uid=current_user.tenant_id,
            activo=payload.activo,
        )
        return _row_to_insumo(dict(zip(INSUMO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{insumo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_insumo(insumo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            deleted = conn.run(
                "DELETE FROM insumos WHERE id = :id AND usuario_id = :uid RETURNING id",
                id=insumo_id, uid=current_user.tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No puedes eliminar este insumo: está en uso en una o más recetas. Desactívalo en su lugar.",
                )
            raise
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")
    finally:
        conn.close()
