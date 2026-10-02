from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import SaborActivoIn, SaborIn, SaborOut

router = APIRouter(prefix="/sabores", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"

SABOR_COLUMNS = ["id", "nombre", "activo"]


def _row_to_sabor(row: dict) -> SaborOut:
    return SaborOut(id=row["id"], nombre=row["nombre"], activo=row["activo"])


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
                f"INSERT INTO sabores (usuario_id, nombre) VALUES (:uid, :nombre) "
                f"RETURNING {', '.join(SABOR_COLUMNS)}",
                uid=current_user.tenant_id, nombre=payload.nombre.strip(),
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
                f"UPDATE sabores SET nombre = :nombre WHERE id = :id AND usuario_id = :uid "
                f"RETURNING {', '.join(SABOR_COLUMNS)}",
                id=sabor_id, uid=current_user.tenant_id, nombre=payload.nombre.strip(),
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
