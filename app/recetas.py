import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    CategoriaRecetaIn,
    CategoriaRecetaOut,
    RecetaActivoIn,
    RecetaEstadisticasOut,
    RecetaIn,
    RecetaIngredienteOut,
    RecetaOut,
    RecetaSaborOut,
    RecetaSaboresUpdateIn,
    RecetaToppingOut,
    RecetaToppingsUpdateIn,
)

router = APIRouter(prefix="/recetas", dependencies=[Depends(get_current_user)])

FOREIGN_KEY_VIOLATION = "23503"

CATEGORIA_COLUMNS = ["id", "key", "label"]
RECETA_COLUMNS = [
    "id", "nombre", "descripcion", "categoria_key", "tiempo_preparacion",
    "porciones", "precio_venta", "activo", "created_at", "imagen_url",
]

INGREDIENTE_SELECT = """
    SELECT ri.id_insumo, i.nombre, i.unidad_medida, ri.cantidad, i.precio_unitario
    FROM receta_insumos ri
    JOIN insumos i ON i.id = ri.id_insumo
    WHERE ri.id_receta = :id_receta
    ORDER BY i.nombre
"""

SABOR_DE_RECETA_SELECT = """
    SELECT s.id, s.nombre, s.activo, rs.precio_adicional
    FROM receta_sabores rs
    JOIN sabores s ON s.id = rs.id_sabor
    WHERE rs.id_receta = :id_receta
    ORDER BY s.nombre
"""

TOPPING_DE_RECETA_SELECT = """
    SELECT t.id, t.nombre, t.activo, rt.precio_adicional, t.foto_url
    FROM receta_toppings rt
    JOIN toppings t ON t.id = rt.id_topping
    WHERE rt.id_receta = :id_receta
    ORDER BY t.nombre
"""


def _row_to_categoria(row: dict) -> CategoriaRecetaOut:
    return CategoriaRecetaOut(id=row["id"], key=row["key"], label=row["label"])


def _slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFD", label.strip().lower())
    without_accents = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", without_accents).strip("-")
    return slug or "categoria"


def _unique_categoria_key(conn, usuario_id: int, label: str) -> str:
    base = _slugify(label)[:45]
    candidate = base
    suffix = 1
    while conn.run(
        "SELECT 1 FROM receta_categorias WHERE usuario_id = :uid AND key = :k", uid=usuario_id, k=candidate
    ):
        suffix += 1
        candidate = f"{base}-{suffix}"[:50]
    return candidate


@router.get("/categorias", response_model=list[CategoriaRecetaOut])
def list_categorias(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(CATEGORIA_COLUMNS)} FROM receta_categorias WHERE usuario_id = :uid "
            "ORDER BY orden, id",
            uid=current_user.tenant_id,
        )
        return [_row_to_categoria(dict(zip(CATEGORIA_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("/categorias", response_model=CategoriaRecetaOut, status_code=status.HTTP_201_CREATED)
def create_categoria(payload: CategoriaRecetaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        key = _unique_categoria_key(conn, current_user.tenant_id, payload.label)
        max_orden = conn.run(
            "SELECT COALESCE(MAX(orden), 0) FROM receta_categorias WHERE usuario_id = :uid", uid=current_user.tenant_id
        )[0][0]
        rows = conn.run(
            f"INSERT INTO receta_categorias (usuario_id, key, label, orden) VALUES (:uid, :key, :label, :orden) "
            f"RETURNING {', '.join(CATEGORIA_COLUMNS)}",
            uid=current_user.tenant_id,
            key=key,
            label=payload.label.strip(),
            orden=max_orden + 1,
        )
        return _row_to_categoria(dict(zip(CATEGORIA_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/categorias/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(categoria_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        if conn.run(
            "SELECT COUNT(*) FROM receta_categorias WHERE usuario_id = :uid", uid=current_user.tenant_id
        )[0][0] <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debe quedar al menos una categoría")
        try:
            deleted = conn.run(
                "DELETE FROM receta_categorias WHERE id = :id AND usuario_id = :uid RETURNING id",
                id=categoria_id, uid=current_user.tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No puedes quitar esta categoría: todavía tiene recetas asignadas",
                )
            raise
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    finally:
        conn.close()


def _receta_select(where: str = "") -> str:
    return (
        "SELECT recetas.id, recetas.nombre, recetas.descripcion, receta_categorias.key AS categoria_key, "
        "recetas.tiempo_preparacion, recetas.porciones, recetas.precio_venta, recetas.activo, recetas.created_at, "
        "recetas.imagen_url "
        "FROM recetas JOIN receta_categorias ON receta_categorias.id = recetas.categoria_id " + where
    )


def _categoria_id_for_key(conn, usuario_id: int, key: str) -> int:
    rows = conn.run(
        "SELECT id FROM receta_categorias WHERE usuario_id = :uid AND key = :k", uid=usuario_id, k=key
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La categoría indicada no existe")
    return rows[0][0]


def _get_ingredientes(conn, receta_id: int) -> list[RecetaIngredienteOut]:
    rows = conn.run(INGREDIENTE_SELECT, id_receta=receta_id)
    return [
        RecetaIngredienteOut(
            id_insumo=r[0], insumo_nombre=r[1], unidad_medida=r[2],
            cantidad=float(r[3]), costo=round(float(r[3]) * float(r[4]), 2),
        )
        for r in rows
    ]


def _get_sabores(conn, receta_id: int) -> list[RecetaSaborOut]:
    rows = conn.run(SABOR_DE_RECETA_SELECT, id_receta=receta_id)
    return [RecetaSaborOut(id=r[0], nombre=r[1], activo=r[2], precio_adicional=float(r[3])) for r in rows]


def _get_toppings(conn, receta_id: int) -> list[RecetaToppingOut]:
    rows = conn.run(TOPPING_DE_RECETA_SELECT, id_receta=receta_id)
    return [
        RecetaToppingOut(id=r[0], nombre=r[1], activo=r[2], precio_adicional=float(r[3]), foto_url=r[4])
        for r in rows
    ]


def _ingredientes_por_receta(conn, receta_ids: list[int]) -> dict[int, list[RecetaIngredienteOut]]:
    """Ingredientes de varias recetas en una sola consulta, agrupados por receta_id — usado por
    list_recetas para no pedirlos receta por receta (evita el N+1 que hacía lento el listado)."""
    agrupado: dict[int, list[RecetaIngredienteOut]] = {rid: [] for rid in receta_ids}
    if not receta_ids:
        return agrupado
    rows = conn.run(
        "SELECT ri.id_receta, ri.id_insumo, i.nombre, i.unidad_medida, ri.cantidad, i.precio_unitario "
        "FROM receta_insumos ri JOIN insumos i ON i.id = ri.id_insumo "
        "WHERE ri.id_receta = ANY(:ids) ORDER BY i.nombre",
        ids=receta_ids,
    )
    for r in rows:
        agrupado[r[0]].append(
            RecetaIngredienteOut(
                id_insumo=r[1], insumo_nombre=r[2], unidad_medida=r[3],
                cantidad=float(r[4]), costo=round(float(r[4]) * float(r[5]), 2),
            )
        )
    return agrupado


def _sabores_por_receta_admin(conn, receta_ids: list[int]) -> dict[int, list[RecetaSaborOut]]:
    """Igual que _get_sabores pero para varias recetas en una sola consulta. A diferencia de
    sabores_por_receta() (en app.sabores, usada por el catálogo de pedidos), no filtra por activo:
    las páginas de administración necesitan ver también los sabores desactivados que sigan asociados."""
    agrupado: dict[int, list[RecetaSaborOut]] = {rid: [] for rid in receta_ids}
    if not receta_ids:
        return agrupado
    rows = conn.run(
        "SELECT rs.id_receta, s.id, s.nombre, s.activo, rs.precio_adicional "
        "FROM receta_sabores rs JOIN sabores s ON s.id = rs.id_sabor "
        "WHERE rs.id_receta = ANY(:ids) ORDER BY s.nombre",
        ids=receta_ids,
    )
    for r in rows:
        agrupado[r[0]].append(RecetaSaborOut(id=r[1], nombre=r[2], activo=r[3], precio_adicional=float(r[4])))
    return agrupado


def _toppings_por_receta_admin(conn, receta_ids: list[int]) -> dict[int, list[RecetaToppingOut]]:
    """Igual que _get_toppings pero para varias recetas en una sola consulta (ver nota de
    _sabores_por_receta_admin sobre por qué no reutiliza la versión filtrada por activo)."""
    agrupado: dict[int, list[RecetaToppingOut]] = {rid: [] for rid in receta_ids}
    if not receta_ids:
        return agrupado
    rows = conn.run(
        "SELECT rt.id_receta, t.id, t.nombre, t.activo, rt.precio_adicional, t.foto_url "
        "FROM receta_toppings rt JOIN toppings t ON t.id = rt.id_topping "
        "WHERE rt.id_receta = ANY(:ids) ORDER BY t.nombre",
        ids=receta_ids,
    )
    for r in rows:
        agrupado[r[0]].append(
            RecetaToppingOut(id=r[1], nombre=r[2], activo=r[3], precio_adicional=float(r[4]), foto_url=r[5])
        )
    return agrupado


def _build_receta_out(
    row: dict,
    ingredientes: list[RecetaIngredienteOut],
    sabores: list[RecetaSaborOut],
    toppings: list[RecetaToppingOut],
) -> RecetaOut:
    costo_total = round(sum(i.costo for i in ingredientes), 2)
    precio_venta = float(row["precio_venta"])
    return RecetaOut(
        id=row["id"], nombre=row["nombre"], descripcion=row["descripcion"],
        categoria=row["categoria_key"], tiempo_preparacion=row["tiempo_preparacion"],
        porciones=row["porciones"], precio_venta=precio_venta, activo=row["activo"],
        created_at=row["created_at"], imagen_url=row["imagen_url"],
        ingredientes=ingredientes, sabores=sabores, toppings=toppings,
        costo_total=costo_total, margen=round(precio_venta - costo_total, 2),
    )


def _row_to_receta(conn, row: dict) -> RecetaOut:
    receta_id = row["id"]
    return _build_receta_out(row, _get_ingredientes(conn, receta_id), _get_sabores(conn, receta_id), _get_toppings(conn, receta_id))


@router.get("", response_model=list[RecetaOut])
def list_recetas(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                _receta_select(
                    "WHERE recetas.usuario_id = :uid AND (recetas.nombre ILIKE :q OR receta_categorias.label ILIKE :q "
                    "OR recetas.descripcion ILIKE :q) ORDER BY recetas.nombre"
                ),
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                _receta_select("WHERE recetas.usuario_id = :uid ORDER BY recetas.nombre"), uid=current_user.tenant_id
            )
        # Trae ingredientes/sabores/toppings de TODAS las recetas en 3 consultas en vez de 3 por
        # receta (antes era 1+3N consultas — con 60-100 productos eso eran 200+ idas y vueltas a
        # la base de datos, la causa de que Toppings/Sabores/Recetas tardaran en cargar).
        recetas = [dict(zip(RECETA_COLUMNS, r)) for r in rows]
        receta_ids = [r["id"] for r in recetas]
        ingredientes_map = _ingredientes_por_receta(conn, receta_ids)
        sabores_map = _sabores_por_receta_admin(conn, receta_ids)
        toppings_map = _toppings_por_receta_admin(conn, receta_ids)
        return [
            _build_receta_out(r, ingredientes_map[r["id"]], sabores_map[r["id"]], toppings_map[r["id"]])
            for r in recetas
        ]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=RecetaEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE activo), COUNT(DISTINCT categoria_id) "
            "FROM recetas WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        ingredientes = conn.run(
            "SELECT COUNT(*) FROM receta_insumos ri JOIN recetas r ON r.id = ri.id_receta "
            "WHERE r.usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0][0]
        return RecetaEstadisticasOut(
            total=row[0], activas=row[1], categorias=row[2], ingredientes_configurados=ingredientes
        )
    finally:
        conn.close()


def _get_receta_or_404(conn, usuario_id: int, receta_id: int) -> dict:
    rows = conn.run(
        _receta_select("WHERE recetas.id = :id AND recetas.usuario_id = :uid"), id=receta_id, uid=usuario_id
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receta no encontrada")
    return dict(zip(RECETA_COLUMNS, rows[0]))


def _set_ingredientes(conn, usuario_id: int, receta_id: int, ingredientes) -> None:
    conn.run("DELETE FROM receta_insumos WHERE id_receta = :id", id=receta_id)
    vistos = set()
    for ing in ingredientes:
        if ing.id_insumo in vistos:
            continue
        vistos.add(ing.id_insumo)
        existe = conn.run(
            "SELECT 1 FROM insumos WHERE id = :id AND usuario_id = :uid", id=ing.id_insumo, uid=usuario_id
        )
        if not existe:
            continue
        conn.run(
            "INSERT INTO receta_insumos (id_receta, id_insumo, cantidad) VALUES (:receta, :insumo, :cantidad)",
            receta=receta_id,
            insumo=ing.id_insumo,
            cantidad=ing.cantidad,
        )


def _set_sabores(conn, usuario_id: int, receta_id: int, sabores: list) -> None:
    conn.run("DELETE FROM receta_sabores WHERE id_receta = :id", id=receta_id)
    vistos: set[int] = set()
    for s in sabores:
        if s.id in vistos:
            continue
        vistos.add(s.id)
        existe = conn.run(
            "SELECT 1 FROM sabores WHERE id = :id AND usuario_id = :uid", id=s.id, uid=usuario_id
        )
        if not existe:
            continue
        conn.run(
            "INSERT INTO receta_sabores (id_receta, id_sabor, precio_adicional) VALUES (:receta, :sabor, :precio)",
            receta=receta_id, sabor=s.id, precio=s.precio_adicional,
        )


def _set_toppings(conn, usuario_id: int, receta_id: int, toppings: list) -> None:
    conn.run("DELETE FROM receta_toppings WHERE id_receta = :id", id=receta_id)
    vistos: set[int] = set()
    for t in toppings:
        if t.id in vistos:
            continue
        vistos.add(t.id)
        existe = conn.run(
            "SELECT 1 FROM toppings WHERE id = :id AND usuario_id = :uid", id=t.id, uid=usuario_id
        )
        if not existe:
            continue
        conn.run(
            "INSERT INTO receta_toppings (id_receta, id_topping, precio_adicional) VALUES (:receta, :topping, :precio)",
            receta=receta_id, topping=t.id, precio=t.precio_adicional,
        )


@router.get("/{receta_id}", response_model=RecetaOut)
def get_receta(receta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_receta(conn, _get_receta_or_404(conn, current_user.tenant_id, receta_id))
    finally:
        conn.close()


@router.post("", response_model=RecetaOut, status_code=status.HTTP_201_CREATED)
def create_receta(payload: RecetaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        categoria_id = _categoria_id_for_key(conn, current_user.tenant_id, payload.categoria)
        rows = conn.run(
            "INSERT INTO recetas (usuario_id, nombre, descripcion, categoria_id, tiempo_preparacion, porciones, "
            "precio_venta, activo, imagen_url) "
            "VALUES (:uid, :nombre, :descripcion, :categoria_id, :tiempo, :porciones, :precio, :activo, :imagen_url) "
            "RETURNING id",
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria_id=categoria_id,
            tiempo=payload.tiempo_preparacion,
            porciones=payload.porciones,
            precio=payload.precio_venta,
            activo=payload.activo,
            imagen_url=payload.imagen_url,
        )
        receta_id = rows[0][0]
        _set_ingredientes(conn, current_user.tenant_id, receta_id, payload.ingredientes)
        _set_sabores(conn, current_user.tenant_id, receta_id, payload.sabores)
        _set_toppings(conn, current_user.tenant_id, receta_id, payload.toppings)
        return _row_to_receta(conn, _get_receta_or_404(conn, current_user.tenant_id, receta_id))
    finally:
        conn.close()


@router.put("/{receta_id}", response_model=RecetaOut)
def update_receta(receta_id: int, payload: RecetaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_receta_or_404(conn, current_user.tenant_id, receta_id)
        categoria_id = _categoria_id_for_key(conn, current_user.tenant_id, payload.categoria)
        conn.run(
            "UPDATE recetas SET nombre = :nombre, descripcion = :descripcion, categoria_id = :categoria_id, "
            "tiempo_preparacion = :tiempo, porciones = :porciones, precio_venta = :precio, activo = :activo, "
            "imagen_url = :imagen_url "
            "WHERE id = :id AND usuario_id = :uid",
            id=receta_id,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            descripcion=payload.descripcion.strip(),
            categoria_id=categoria_id,
            tiempo=payload.tiempo_preparacion,
            porciones=payload.porciones,
            precio=payload.precio_venta,
            activo=payload.activo,
            imagen_url=payload.imagen_url,
        )
        _set_ingredientes(conn, current_user.tenant_id, receta_id, payload.ingredientes)
        _set_sabores(conn, current_user.tenant_id, receta_id, payload.sabores)
        _set_toppings(conn, current_user.tenant_id, receta_id, payload.toppings)
        return _row_to_receta(conn, _get_receta_or_404(conn, current_user.tenant_id, receta_id))
    finally:
        conn.close()


@router.put("/{receta_id}/sabores", response_model=list[RecetaSaborOut])
def set_receta_sabores(
    receta_id: int, payload: RecetaSaboresUpdateIn, current_user: UserOut = Depends(get_current_user)
):
    """Reemplaza solo los sabores de esta receta — a diferencia de PUT /recetas/{id}, no toca
    el resto del producto. Pensada para la página de Sabores: ahí se elige primero el producto
    y luego se arman (o reutilizan) sus sabores, sin tener que reenviar la receta completa."""
    conn = get_connection()
    try:
        _get_receta_or_404(conn, current_user.tenant_id, receta_id)
        _set_sabores(conn, current_user.tenant_id, receta_id, payload.sabores)
        return _get_sabores(conn, receta_id)
    finally:
        conn.close()


@router.put("/{receta_id}/toppings", response_model=list[RecetaToppingOut])
def set_receta_toppings(
    receta_id: int, payload: RecetaToppingsUpdateIn, current_user: UserOut = Depends(get_current_user)
):
    """Reemplaza solo los toppings de esta receta — a diferencia de PUT /recetas/{id}, no toca
    el resto del producto. Pensada para la página de Toppings: ahí se elige primero el producto
    y luego se arman (o reutilizan) sus toppings, sin tener que reenviar la receta completa."""
    conn = get_connection()
    try:
        _get_receta_or_404(conn, current_user.tenant_id, receta_id)
        _set_toppings(conn, current_user.tenant_id, receta_id, payload.toppings)
        return _get_toppings(conn, receta_id)
    finally:
        conn.close()


@router.patch("/{receta_id}/activo", response_model=RecetaOut)
def toggle_activo(receta_id: int, payload: RecetaActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_receta_or_404(conn, current_user.tenant_id, receta_id)
        conn.run(
            "UPDATE recetas SET activo = :activo WHERE id = :id AND usuario_id = :uid",
            id=receta_id, uid=current_user.tenant_id, activo=payload.activo,
        )
        return _row_to_receta(conn, _get_receta_or_404(conn, current_user.tenant_id, receta_id))
    finally:
        conn.close()


@router.delete("/{receta_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receta(receta_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM recetas WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=receta_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receta no encontrada")
    finally:
        conn.close()
