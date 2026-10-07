from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.imagenes import generar_thumbnail
from app.schemas import RecetaToppingOut, ToppingActivoIn, ToppingIn, ToppingOut

router = APIRouter(prefix="/toppings", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"

TOPPING_COLUMNS = ["id", "nombre", "activo", "foto_url", "foto_thumb_url"]


def _row_to_topping(row: dict, thumbnail: bool = False) -> ToppingOut:
    foto_url = (row["foto_thumb_url"] or row["foto_url"]) if thumbnail else row["foto_url"]
    return ToppingOut(id=row["id"], nombre=row["nombre"], activo=row["activo"], foto_url=foto_url)


def toppings_por_receta(conn, receta_ids: list[int]) -> dict[int, list[RecetaToppingOut]]:
    """Toppings activos de varias recetas en una sola consulta, agrupados por receta_id —
    para armar un catálogo sin pedirlos receta por receta (N+1). Incluye el valor adicional
    que ese topping tiene específicamente en cada receta. Usa la miniatura (no la foto completa):
    este catálogo es para elegir el topping al armar un pedido, no para verlo en grande."""
    agrupado: dict[int, list[RecetaToppingOut]] = {rid: [] for rid in receta_ids}
    if not receta_ids:
        return agrupado
    rows = conn.run(
        "SELECT rt.id_receta, t.id, t.nombre, t.activo, rt.precio_adicional, t.foto_url, t.foto_thumb_url "
        "FROM receta_toppings rt JOIN toppings t ON t.id = rt.id_topping "
        "WHERE rt.id_receta = ANY(:ids) AND t.activo = true "
        "ORDER BY t.nombre",
        ids=receta_ids,
    )
    for r in rows:
        agrupado[r[0]].append(
            RecetaToppingOut(id=r[1], nombre=r[2], activo=r[3], precio_adicional=float(r[4]), foto_url=r[6] or r[5])
        )
    return agrupado


@router.get("", response_model=list[ToppingOut])
def list_toppings(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(TOPPING_COLUMNS)} FROM toppings WHERE usuario_id = :uid ORDER BY nombre",
            uid=current_user.tenant_id,
        )
        return [_row_to_topping(dict(zip(TOPPING_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=ToppingOut, status_code=status.HTTP_201_CREATED)
def create_topping(payload: ToppingIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            rows = conn.run(
                f"INSERT INTO toppings (usuario_id, nombre, foto_url, foto_thumb_url) "
                f"VALUES (:uid, :nombre, :foto_url, :foto_thumb_url) "
                f"RETURNING {', '.join(TOPPING_COLUMNS)}",
                uid=current_user.tenant_id, nombre=payload.nombre.strip(), foto_url=payload.foto_url,
                foto_thumb_url=generar_thumbnail(payload.foto_url),
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un topping con ese nombre")
            raise
        return _row_to_topping(dict(zip(TOPPING_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{topping_id}", response_model=ToppingOut)
def update_topping(topping_id: int, payload: ToppingIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            rows = conn.run(
                f"UPDATE toppings SET nombre = :nombre, foto_url = :foto_url, foto_thumb_url = :foto_thumb_url "
                f"WHERE id = :id AND usuario_id = :uid "
                f"RETURNING {', '.join(TOPPING_COLUMNS)}",
                id=topping_id, uid=current_user.tenant_id, nombre=payload.nombre.strip(), foto_url=payload.foto_url,
                foto_thumb_url=generar_thumbnail(payload.foto_url),
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un topping con ese nombre")
            raise
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topping no encontrado")
        return _row_to_topping(dict(zip(TOPPING_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{topping_id}/activo", response_model=ToppingOut)
def toggle_activo(topping_id: int, payload: ToppingActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"UPDATE toppings SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(TOPPING_COLUMNS)}",
            id=topping_id, uid=current_user.tenant_id, activo=payload.activo,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topping no encontrado")
        return _row_to_topping(dict(zip(TOPPING_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{topping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topping(topping_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM toppings WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=topping_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topping no encontrado")
    finally:
        conn.close()
