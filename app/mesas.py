import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import MesaActivoIn, MesaEstadoIn, MesaIn, MesaOut, ZonaIn, ZonaOut

router = APIRouter(dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"

ZONA_COLUMNS = ["id", "key", "label"]
MESA_COLUMNS = ["id", "numero", "nombre", "capacidad", "estado", "activo", "zona_key"]


def _row_to_zona(row: dict) -> ZonaOut:
    return ZonaOut(id=row["id"], key=row["key"], label=row["label"])


def _row_to_mesa(row: dict) -> MesaOut:
    return MesaOut(
        id=row["id"],
        numero=row["numero"],
        nombre=row["nombre"],
        capacidad=row["capacidad"],
        zona=row["zona_key"],
        estado=row["estado"],
        activo=row["activo"],
    )


def _slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFD", label.strip().lower())
    without_accents = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", without_accents).strip("-")
    return slug or "zona"


def _unique_zona_key(conn, usuario_id: int, label: str) -> str:
    base = _slugify(label)[:45]
    candidate = base
    suffix = 1
    while conn.run("SELECT 1 FROM zonas WHERE usuario_id = :uid AND key = :k", uid=usuario_id, k=candidate):
        suffix += 1
        candidate = f"{base}-{suffix}"[:50]
    return candidate


@router.get("/zonas", response_model=list[ZonaOut])
def list_zonas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(ZONA_COLUMNS)} FROM zonas WHERE usuario_id = :uid ORDER BY orden, id",
            uid=current_user.tenant_id,
        )
        return [_row_to_zona(dict(zip(ZONA_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("/zonas", response_model=ZonaOut, status_code=status.HTTP_201_CREATED)
def create_zona(payload: ZonaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        key = _unique_zona_key(conn, current_user.tenant_id, payload.label)
        max_orden = conn.run(
            "SELECT COALESCE(MAX(orden), 0) FROM zonas WHERE usuario_id = :uid", uid=current_user.tenant_id
        )[0][0]
        rows = conn.run(
            f"INSERT INTO zonas (usuario_id, key, label, orden) VALUES (:uid, :key, :label, :orden) "
            f"RETURNING {', '.join(ZONA_COLUMNS)}",
            uid=current_user.tenant_id,
            key=key,
            label=payload.label.strip(),
            orden=max_orden + 1,
        )
        return _row_to_zona(dict(zip(ZONA_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/zonas/{zona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zona(zona_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        if conn.run("SELECT COUNT(*) FROM zonas WHERE usuario_id = :uid", uid=current_user.tenant_id)[0][0] <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debe quedar al menos una zona")
        try:
            deleted = conn.run(
                "DELETE FROM zonas WHERE id = :id AND usuario_id = :uid RETURNING id",
                id=zona_id, uid=current_user.tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No puedes quitar esta zona: todavía tiene mesas asignadas",
                )
            raise
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zona no encontrada")
    finally:
        conn.close()


def _mesa_select(where: str = "") -> str:
    return (
        "SELECT mesas.id, mesas.numero, mesas.nombre, mesas.capacidad, mesas.estado, mesas.activo, "
        "zonas.key AS zona_key "
        "FROM mesas JOIN zonas ON zonas.id = mesas.zona_id " + where
    )


@router.get("/mesas", response_model=list[MesaOut])
def list_mesas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            _mesa_select("WHERE mesas.usuario_id = :uid ORDER BY mesas.numero"), uid=current_user.tenant_id
        )
        return [_row_to_mesa(dict(zip(MESA_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


def _zona_id_for_key(conn, usuario_id: int, key: str) -> int:
    rows = conn.run("SELECT id FROM zonas WHERE usuario_id = :uid AND key = :k", uid=usuario_id, k=key)
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La zona indicada no existe")
    return rows[0][0]


@router.post("/mesas", response_model=MesaOut, status_code=status.HTTP_201_CREATED)
def create_mesa(payload: MesaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        zona_id = _zona_id_for_key(conn, current_user.tenant_id, payload.zona)
        try:
            conn.run(
                "INSERT INTO mesas (usuario_id, numero, nombre, capacidad, zona_id, estado, activo) "
                "VALUES (:uid, :numero, :nombre, :capacidad, :zona_id, :estado, :activo) RETURNING id",
                uid=current_user.tenant_id,
                numero=payload.numero,
                nombre=payload.nombre,
                capacidad=payload.capacidad,
                zona_id=zona_id,
                estado=payload.estado,
                activo=payload.activo,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una mesa con ese número")
            raise
        rows = conn.run(
            _mesa_select("WHERE mesas.usuario_id = :uid AND mesas.numero = :numero"),
            uid=current_user.tenant_id, numero=payload.numero,
        )
        return _row_to_mesa(dict(zip(MESA_COLUMNS, rows[0])))
    finally:
        conn.close()


def _get_mesa_or_404(conn, usuario_id: int, mesa_id: int) -> dict:
    rows = conn.run(
        _mesa_select("WHERE mesas.id = :id AND mesas.usuario_id = :uid"), id=mesa_id, uid=usuario_id
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")
    return dict(zip(MESA_COLUMNS, rows[0]))


@router.put("/mesas/{mesa_id}", response_model=MesaOut)
def update_mesa(mesa_id: int, payload: MesaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_mesa_or_404(conn, current_user.tenant_id, mesa_id)
        zona_id = _zona_id_for_key(conn, current_user.tenant_id, payload.zona)
        try:
            conn.run(
                "UPDATE mesas SET numero = :numero, nombre = :nombre, capacidad = :capacidad, "
                "zona_id = :zona_id, estado = :estado, activo = :activo WHERE id = :id AND usuario_id = :uid",
                id=mesa_id,
                uid=current_user.tenant_id,
                numero=payload.numero,
                nombre=payload.nombre,
                capacidad=payload.capacidad,
                zona_id=zona_id,
                estado=payload.estado,
                activo=payload.activo,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una mesa con ese número")
            raise
        return _row_to_mesa(_get_mesa_or_404(conn, current_user.tenant_id, mesa_id))
    finally:
        conn.close()


@router.patch("/mesas/{mesa_id}/estado", response_model=MesaOut)
def update_mesa_estado(mesa_id: int, payload: MesaEstadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_mesa_or_404(conn, current_user.tenant_id, mesa_id)
        conn.run(
            "UPDATE mesas SET estado = :estado WHERE id = :id AND usuario_id = :uid",
            id=mesa_id, uid=current_user.tenant_id, estado=payload.estado,
        )
        return _row_to_mesa(_get_mesa_or_404(conn, current_user.tenant_id, mesa_id))
    finally:
        conn.close()


@router.patch("/mesas/{mesa_id}/activo", response_model=MesaOut)
def update_mesa_activo(mesa_id: int, payload: MesaActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_mesa_or_404(conn, current_user.tenant_id, mesa_id)
        conn.run(
            "UPDATE mesas SET activo = :activo WHERE id = :id AND usuario_id = :uid",
            id=mesa_id, uid=current_user.tenant_id, activo=payload.activo,
        )
        return _row_to_mesa(_get_mesa_or_404(conn, current_user.tenant_id, mesa_id))
    finally:
        conn.close()


@router.delete("/mesas/{mesa_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mesa(mesa_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            deleted = conn.run(
                "DELETE FROM mesas WHERE id = :id AND usuario_id = :uid RETURNING id",
                id=mesa_id, uid=current_user.tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No puedes eliminar esta mesa: tiene órdenes registradas. Desactívala en su lugar.",
                )
            raise
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")
    finally:
        conn.close()
