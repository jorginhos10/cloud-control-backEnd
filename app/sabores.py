from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.imagenes import generar_thumbnail
from app.schemas import RecetaSaborOut, SaborActivoIn, SaborIn, SaborOut

router = APIRouter(prefix="/sabores", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"

SABOR_COLUMNS = ["id", "nombre", "activo", "foto_url", "foto_thumb_url"]


def _row_to_sabor(row: dict) -> SaborOut:
    return SaborOut(id=row["id"], nombre=row["nombre"], activo=row["activo"], foto_url=row["foto_url"])


def sabores_por_receta(conn, receta_ids: list[int]) -> dict[int, list[RecetaSaborOut]]:
    """Sabores activos de varias recetas en una sola consulta, agrupados por receta_id —
    para armar un catálogo sin pedirlos receta por receta (N+1). Incluye el valor adicional
    que ese sabor tiene específicamente en cada receta. Usa la miniatura (no la foto completa):
    este catálogo es para elegir el sabor al armar un pedido, no para verlo en grande."""
    agrupado: dict[int, list[RecetaSaborOut]] = {rid: [] for rid in receta_ids}
    if not receta_ids:
        return agrupado
    rows = conn.run(
        "SELECT rs.id_receta, s.id, s.nombre, s.activo, rs.precio_adicional, s.foto_url, s.foto_thumb_url "
        "FROM receta_sabores rs JOIN sabores s ON s.id = rs.id_sabor "
        "WHERE rs.id_receta = ANY(:ids) AND s.activo = true "
        "ORDER BY s.nombre",
        ids=receta_ids,
    )
    for r in rows:
        agrupado[r[0]].append(
            RecetaSaborOut(id=r[1], nombre=r[2], activo=r[3], precio_adicional=float(r[4]), foto_url=r[6] or r[5])
        )
    return agrupado


@router.get("", response_model=list[SaborOut])
def list_sabores(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(SABOR_COLUMNS)} FROM sabores WHERE usuario_id = :uid ORDER BY nombre",
            uid=current_user.tenant_id,
        )
        return [_row_to_sabor(dict(zip(SABOR_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=SaborOut, status_code=status.HTTP_201_CREATED)
def create_sabor(payload: SaborIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            rows = conn.run(
                f"INSERT INTO sabores (usuario_id, nombre, foto_url, foto_thumb_url) "
                f"VALUES (:uid, :nombre, :foto_url, :foto_thumb_url) "
                f"RETURNING {', '.join(SABOR_COLUMNS)}",
                uid=current_user.tenant_id, nombre=payload.nombre.strip(), foto_url=payload.foto_url,
                foto_thumb_url=generar_thumbnail(payload.foto_url),
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un sabor con ese nombre")
            raise
        return _row_to_sabor(dict(zip(SABOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{sabor_id}", response_model=SaborOut)
def update_sabor(sabor_id: int, payload: SaborIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            rows = conn.run(
                f"UPDATE sabores SET nombre = :nombre, foto_url = :foto_url, foto_thumb_url = :foto_thumb_url "
                f"WHERE id = :id AND usuario_id = :uid "
                f"RETURNING {', '.join(SABOR_COLUMNS)}",
                id=sabor_id, uid=current_user.tenant_id, nombre=payload.nombre.strip(), foto_url=payload.foto_url,
                foto_thumb_url=generar_thumbnail(payload.foto_url),
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un sabor con ese nombre")
            raise
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sabor no encontrado")
        return _row_to_sabor(dict(zip(SABOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{sabor_id}/activo", response_model=SaborOut)
def toggle_activo(sabor_id: int, payload: SaborActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"UPDATE sabores SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(SABOR_COLUMNS)}",
            id=sabor_id, uid=current_user.tenant_id, activo=payload.activo,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sabor no encontrado")
        return _row_to_sabor(dict(zip(SABOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{sabor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sabor(sabor_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM sabores WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=sabor_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sabor no encontrado")
    finally:
        conn.close()
