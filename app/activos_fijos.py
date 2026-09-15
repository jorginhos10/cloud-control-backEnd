from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    ActivoFijoActivoIn,
    ActivoFijoEstadisticasOut,
    ActivoFijoEstadoIn,
    ActivoFijoHistorialOut,
    ActivoFijoIn,
    ActivoFijoOut,
)

router = APIRouter(prefix="/activos-fijos", dependencies=[Depends(get_current_user)])

ACTIVO_COLUMNS = [
    "id", "nombre", "descripcion", "categoria", "cantidad", "ubicacion",
    "estado", "valor_unitario", "activo", "created_at",
]


def _row_to_activo(row: dict) -> ActivoFijoOut:
    return ActivoFijoOut(
        id=row["id"],
        nombre=row["nombre"],
        descripcion=row["descripcion"],
        categoria=row["categoria"],
        cantidad=row["cantidad"],
        ubicacion=row["ubicacion"],
        estado=row["estado"],
        valor_unitario=float(row["valor_unitario"]),
        activo=row["activo"],
        created_at=row["created_at"],
    )


@router.get("", response_model=list[ActivoFijoOut])
def list_activos(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                f"SELECT {', '.join(ACTIVO_COLUMNS)} FROM activos_fijos "
                "WHERE usuario_id = :uid AND (nombre ILIKE :q OR categoria ILIKE :q OR ubicacion ILIKE :q OR descripcion ILIKE :q) "
                "ORDER BY nombre",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(ACTIVO_COLUMNS)} FROM activos_fijos WHERE usuario_id = :uid ORDER BY nombre",
                uid=current_user.tenant_id,
            )
        return [_row_to_activo(dict(zip(ACTIVO_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=ActivoFijoEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE activo), "
            "COUNT(*) FILTER (WHERE activo AND estado IN ('danado', 'perdido', 'de_baja')), "
            "COUNT(DISTINCT categoria) "
            "FROM activos_fijos WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return ActivoFijoEstadisticasOut(total=row[0], activos=row[1], danados=row[2], categorias=row[3])
    finally:
        conn.close()


def _get_activo_or_404(conn, usuario_id: int, activo_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(ACTIVO_COLUMNS)} FROM activos_fijos WHERE id = :id AND usuario_id = :uid",
        id=activo_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")
    return dict(zip(ACTIVO_COLUMNS, rows[0]))


@router.get("/{activo_id}", response_model=ActivoFijoOut)
def get_activo(activo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_activo(_get_activo_or_404(conn, current_user.tenant_id, activo_id))
    finally:
        conn.close()


@router.get("/{activo_id}/historial", response_model=list[ActivoFijoHistorialOut])
def get_historial(activo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_activo_or_404(conn, current_user.tenant_id, activo_id)
        rows = conn.run(
            "SELECT h.id, h.estado_anterior, h.estado_nuevo, h.cantidad_anterior, h.cantidad_nueva, h.nota, "
            "h.created_at, u.nombre "
            "FROM activos_fijos_historial h "
            "JOIN usuarios u ON u.id = h.registrado_por_id "
            "WHERE h.activo_id = :id ORDER BY h.created_at DESC",
            id=activo_id,
        )
        columns = ["id", "estado_anterior", "estado_nuevo", "cantidad_anterior", "cantidad_nueva", "nota", "created_at", "registrado_por"]
        return [ActivoFijoHistorialOut(**dict(zip(columns, r))) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=ActivoFijoOut, status_code=status.HTTP_201_CREATED)
def create_activo(payload: ActivoFijoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO activos_fijos (usuario_id, nombre, descripcion, categoria, cantidad, ubicacion, "
            "estado, valor_unitario, activo) "
            "VALUES (:uid, :nombre, :descripcion, :categoria, :cantidad, :ubicacion, :estado, :valor, :activo) "
            f"RETURNING {', '.join(ACTIVO_COLUMNS)}",
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria=payload.categoria,
            cantidad=payload.cantidad,
            ubicacion=payload.ubicacion.strip(),
            estado=payload.estado,
            valor=payload.valor_unitario,
            activo=payload.activo,
        )
        return _row_to_activo(dict(zip(ACTIVO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{activo_id}", response_model=ActivoFijoOut)
def update_activo(activo_id: int, payload: ActivoFijoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_activo_or_404(conn, current_user.tenant_id, activo_id)
        rows = conn.run(
            "UPDATE activos_fijos SET nombre = :nombre, descripcion = :descripcion, categoria = :categoria, "
            "cantidad = :cantidad, ubicacion = :ubicacion, valor_unitario = :valor, activo = :activo "
            f"WHERE id = :id AND usuario_id = :uid RETURNING {', '.join(ACTIVO_COLUMNS)}",
            id=activo_id,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria=payload.categoria,
            cantidad=payload.cantidad,
            ubicacion=payload.ubicacion.strip(),
            valor=payload.valor_unitario,
            activo=payload.activo,
        )
        return _row_to_activo(dict(zip(ACTIVO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{activo_id}/activo", response_model=ActivoFijoOut)
def toggle_activo(activo_id: int, payload: ActivoFijoActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_activo_or_404(conn, current_user.tenant_id, activo_id)
        rows = conn.run(
            f"UPDATE activos_fijos SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(ACTIVO_COLUMNS)}",
            id=activo_id,
            uid=current_user.tenant_id,
            activo=payload.activo,
        )
        return _row_to_activo(dict(zip(ACTIVO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{activo_id}/estado", response_model=ActivoFijoOut)
def registrar_estado(activo_id: int, payload: ActivoFijoEstadoIn, current_user: UserOut = Depends(get_current_user)):
    """Registra un cambio de estado (y opcionalmente de cantidad) dejando huella en el historial."""
    conn = get_connection()
    try:
        actual = _get_activo_or_404(conn, current_user.tenant_id, activo_id)
        cantidad_nueva = payload.cantidad if payload.cantidad is not None else actual["cantidad"]

        conn.run(
            "INSERT INTO activos_fijos_historial "
            "(activo_id, usuario_id, estado_anterior, estado_nuevo, cantidad_anterior, cantidad_nueva, nota, registrado_por_id) "
            "VALUES (:activo_id, :uid, :estado_anterior, :estado_nuevo, :cantidad_anterior, :cantidad_nueva, :nota, :registrado_por)",
            activo_id=activo_id,
            uid=current_user.tenant_id,
            estado_anterior=actual["estado"],
            estado_nuevo=payload.estado,
            cantidad_anterior=actual["cantidad"],
            cantidad_nueva=cantidad_nueva,
            nota=payload.nota.strip(),
            registrado_por=current_user.id,
        )
        rows = conn.run(
            "UPDATE activos_fijos SET estado = :estado, cantidad = :cantidad WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(ACTIVO_COLUMNS)}",
            id=activo_id,
            uid=current_user.tenant_id,
            estado=payload.estado,
            cantidad=cantidad_nueva,
        )
        return _row_to_activo(dict(zip(ACTIVO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{activo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activo(activo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM activos_fijos WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=activo_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")
    finally:
        conn.close()
