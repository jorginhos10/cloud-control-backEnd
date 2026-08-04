import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    MenuDigitalConfigIn,
    MenuDigitalDetalleOut,
    MenuDigitalIn,
    MenuDigitalOut,
    MenuItemOut,
    MenuItemsIn,
)

router = APIRouter(prefix="/menu-digital", dependencies=[Depends(get_current_user)])

MENU_SELECT = """
    SELECT md.id, md.nombre, md.descripcion, md.activo, md.token, md.mesa_id,
           m.numero AS mesa_numero, m.nombre AS mesa_nombre, md.created_at,
           COALESCE(ic.items_count, 0) AS items_count
    FROM menus_digitales md
    LEFT JOIN mesas m ON m.id = md.mesa_id
    LEFT JOIN (
        SELECT menu_id, COUNT(*) AS items_count FROM menu_items GROUP BY menu_id
    ) ic ON ic.menu_id = md.id
"""
MENU_COLUMNS = [
    "id", "nombre", "descripcion", "activo", "token", "mesa_id",
    "mesa_numero", "mesa_nombre", "created_at", "items_count",
]

MENU_ITEMS_SELECT = """
    SELECT mi.receta_id, r.nombre, r.descripcion, rc.label AS categoria, r.precio_venta, mi.orden,
           (
               SELECT MIN(FLOOR(i.cantidad_stock / ri.cantidad))
               FROM receta_insumos ri
               JOIN insumos i ON i.id = ri.id_insumo
               WHERE ri.id_receta = r.id
           ) AS disponible
    FROM menu_items mi
    JOIN recetas r ON r.id = mi.receta_id
    JOIN receta_categorias rc ON rc.id = r.categoria_id
    WHERE mi.menu_id = :id
    ORDER BY mi.orden
"""


def _row_to_menu(row: dict) -> MenuDigitalOut:
    return MenuDigitalOut(
        id=row["id"], nombre=row["nombre"], descripcion=row["descripcion"], activo=row["activo"],
        token=row["token"], mesa_id=row["mesa_id"], mesa_numero=row["mesa_numero"],
        mesa_nombre=row["mesa_nombre"], created_at=row["created_at"], items_count=row["items_count"],
    )


def _get_items(conn, menu_id: int) -> list[MenuItemOut]:
    rows = conn.run(MENU_ITEMS_SELECT, id=menu_id)
    return [
        MenuItemOut(
            receta_id=r[0], nombre=r[1], descripcion=r[2], categoria=r[3],
            precio_venta=float(r[4]), orden=r[5], disponible=int(r[6]) if r[6] is not None else None,
        )
        for r in rows
    ]


def _get_menu_or_404(conn, usuario_id: int, menu_id: int) -> dict:
    rows = conn.run(MENU_SELECT + " WHERE md.id = :id AND md.usuario_id = :uid", id=menu_id, uid=usuario_id)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menú no encontrado")
    return dict(zip(MENU_COLUMNS, rows[0]))


@router.get("", response_model=list[MenuDigitalOut])
def list_menus(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(MENU_SELECT + " WHERE md.usuario_id = :uid ORDER BY md.created_at DESC", uid=current_user.tenant_id)
        return [_row_to_menu(dict(zip(MENU_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/{menu_id}", response_model=MenuDigitalDetalleOut)
def get_menu(menu_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = _get_menu_or_404(conn, current_user.tenant_id, menu_id)
        return MenuDigitalDetalleOut(**_row_to_menu(row).model_dump(), items=_get_items(conn, menu_id))
    finally:
        conn.close()


@router.post("", response_model=MenuDigitalOut, status_code=status.HTTP_201_CREATED)
def create_menu(payload: MenuDigitalIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        token = secrets.token_hex(16)
        rows = conn.run(
            "INSERT INTO menus_digitales (usuario_id, nombre, descripcion, activo, token) "
            "VALUES (:uid, :nombre, :descripcion, :activo, :token) RETURNING id",
            uid=current_user.tenant_id, nombre=payload.nombre.strip(), descripcion=payload.descripcion.strip(),
            activo=payload.activo, token=token,
        )
        return _row_to_menu(_get_menu_or_404(conn, current_user.tenant_id, rows[0][0]))
    finally:
        conn.close()


@router.put("/{menu_id}", response_model=MenuDigitalOut)
def update_menu(menu_id: int, payload: MenuDigitalIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_menu_or_404(conn, current_user.tenant_id, menu_id)
        conn.run(
            "UPDATE menus_digitales SET nombre = :nombre, descripcion = :descripcion, activo = :activo "
            "WHERE id = :id AND usuario_id = :uid",
            id=menu_id, uid=current_user.tenant_id, nombre=payload.nombre.strip(), descripcion=payload.descripcion.strip(),
            activo=payload.activo,
        )
        return _row_to_menu(_get_menu_or_404(conn, current_user.tenant_id, menu_id))
    finally:
        conn.close()


@router.patch("/{menu_id}/configurar", response_model=MenuDigitalOut)
def configurar_menu(menu_id: int, payload: MenuDigitalConfigIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_menu_or_404(conn, current_user.tenant_id, menu_id)
        if payload.mesa_id is not None:
            existe = conn.run(
                "SELECT 1 FROM mesas WHERE id = :id AND usuario_id = :uid",
                id=payload.mesa_id, uid=current_user.tenant_id,
            )
            if not existe:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La mesa indicada no existe")
        conn.run(
            "UPDATE menus_digitales SET nombre = :nombre, mesa_id = :mesa_id WHERE id = :id AND usuario_id = :uid",
            id=menu_id, uid=current_user.tenant_id, nombre=payload.nombre.strip(), mesa_id=payload.mesa_id,
        )
        return _row_to_menu(_get_menu_or_404(conn, current_user.tenant_id, menu_id))
    finally:
        conn.close()


@router.patch("/{menu_id}/toggle", response_model=MenuDigitalOut)
def toggle_menu(menu_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_menu_or_404(conn, current_user.tenant_id, menu_id)
        conn.run(
            "UPDATE menus_digitales SET activo = NOT activo WHERE id = :id AND usuario_id = :uid",
            id=menu_id, uid=current_user.tenant_id,
        )
        return _row_to_menu(_get_menu_or_404(conn, current_user.tenant_id, menu_id))
    finally:
        conn.close()


@router.put("/{menu_id}/items", response_model=MenuDigitalDetalleOut)
def set_items(menu_id: int, payload: MenuItemsIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = _get_menu_or_404(conn, current_user.tenant_id, menu_id)
        conn.run("DELETE FROM menu_items WHERE menu_id = :id", id=menu_id)
        vistos = set()
        orden = 0
        for receta_id in payload.receta_ids:
            if receta_id in vistos:
                continue
            existe = conn.run(
                "SELECT 1 FROM recetas WHERE id = :id AND usuario_id = :uid AND activo = true",
                id=receta_id, uid=current_user.tenant_id,
            )
            if not existe:
                continue
            vistos.add(receta_id)
            conn.run(
                "INSERT INTO menu_items (menu_id, receta_id, orden) VALUES (:mid, :rid, :orden)",
                mid=menu_id, rid=receta_id, orden=orden,
            )
            orden += 1
        menu_data = _row_to_menu(row).model_dump()
        menu_data["items_count"] = len(vistos)
        return MenuDigitalDetalleOut(**menu_data, items=_get_items(conn, menu_id))
    finally:
        conn.close()


@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_menu(menu_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM menus_digitales WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=menu_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menú no encontrado")
    finally:
        conn.close()
