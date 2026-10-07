from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.imagenes import generar_thumbnail
from app.schemas import RecetaToppingOut, ToppingActivoIn, ToppingIn, ToppingInsumoOut, ToppingOut

router = APIRouter(prefix="/toppings", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"

TOPPING_COLUMNS = ["id", "nombre", "activo", "foto_url", "foto_thumb_url"]

INSUMO_DE_TOPPING_SELECT = """
    SELECT ti.id_insumo, i.nombre, i.unidad_medida, ti.cantidad
    FROM topping_insumos ti
    JOIN insumos i ON i.id = ti.id_insumo
    WHERE ti.id_topping = :id_topping
    ORDER BY i.nombre
"""


def _get_insumos_topping(conn, topping_id: int) -> list[ToppingInsumoOut]:
    rows = conn.run(INSUMO_DE_TOPPING_SELECT, id_topping=topping_id)
    return [ToppingInsumoOut(id_insumo=r[0], insumo_nombre=r[1], unidad_medida=r[2], cantidad=float(r[3])) for r in rows]


def _insumos_por_topping(conn, topping_ids: list[int]) -> dict[int, list[ToppingInsumoOut]]:
    """Insumos de varios toppings en una sola consulta, agrupados por topping_id — usado por
    list_toppings para no pedirlos topping por topping (evita el N+1 que ya resolvimos en recetas)."""
    agrupado: dict[int, list[ToppingInsumoOut]] = {tid: [] for tid in topping_ids}
    if not topping_ids:
        return agrupado
    rows = conn.run(
        "SELECT ti.id_topping, ti.id_insumo, i.nombre, i.unidad_medida, ti.cantidad "
        "FROM topping_insumos ti JOIN insumos i ON i.id = ti.id_insumo "
        "WHERE ti.id_topping = ANY(:ids) ORDER BY i.nombre",
        ids=topping_ids,
    )
    for r in rows:
        agrupado[r[0]].append(ToppingInsumoOut(id_insumo=r[1], insumo_nombre=r[2], unidad_medida=r[3], cantidad=float(r[4])))
    return agrupado


def _set_insumos_topping(conn, usuario_id: int, topping_id: int, insumos: list) -> None:
    conn.run("DELETE FROM topping_insumos WHERE id_topping = :id", id=topping_id)
    vistos: set[int] = set()
    for ins in insumos:
        if ins.id_insumo in vistos:
            continue
        vistos.add(ins.id_insumo)
        existe = conn.run(
            "SELECT 1 FROM insumos WHERE id = :id AND usuario_id = :uid", id=ins.id_insumo, uid=usuario_id
        )
        if not existe:
            continue
        conn.run(
            "INSERT INTO topping_insumos (id_topping, id_insumo, cantidad) VALUES (:topping, :insumo, :cantidad)",
            topping=topping_id, insumo=ins.id_insumo, cantidad=ins.cantidad,
        )


def _row_to_topping(row: dict, insumos: list[ToppingInsumoOut], thumbnail: bool = False) -> ToppingOut:
    foto_url = (row["foto_thumb_url"] or row["foto_url"]) if thumbnail else row["foto_url"]
    return ToppingOut(id=row["id"], nombre=row["nombre"], activo=row["activo"], foto_url=foto_url, insumos=insumos)


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
        toppings = [dict(zip(TOPPING_COLUMNS, r)) for r in rows]
        insumos_map = _insumos_por_topping(conn, [t["id"] for t in toppings])
        return [_row_to_topping(t, insumos_map[t["id"]]) for t in toppings]
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
        row = dict(zip(TOPPING_COLUMNS, rows[0]))
        _set_insumos_topping(conn, current_user.tenant_id, row["id"], payload.insumos)
        return _row_to_topping(row, _get_insumos_topping(conn, row["id"]))
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
        row = dict(zip(TOPPING_COLUMNS, rows[0]))
        _set_insumos_topping(conn, current_user.tenant_id, topping_id, payload.insumos)
        return _row_to_topping(row, _get_insumos_topping(conn, topping_id))
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
        row = dict(zip(TOPPING_COLUMNS, rows[0]))
        return _row_to_topping(row, _get_insumos_topping(conn, topping_id))
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
