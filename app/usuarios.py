from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user, get_tenant_id
from app.database import get_connection
from app.schemas import (
    UsuarioActivoIn,
    UsuarioResetPasswordIn,
    UsuarioStaffIn,
    UsuarioStaffOut,
    UsuarioStaffUpdateIn,
)
from app.security import hash_password

router = APIRouter(prefix="/usuarios", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"

STAFF_COLUMNS = ["id", "username", "nombre", "email", "rol", "activo", "propietario", "ultimo_login"]


def _row_to_staff(row: dict) -> UsuarioStaffOut:
    return UsuarioStaffOut(
        id=row["id"], username=row["username"], nombre=row["nombre"], email=row["email"],
        rol=row["rol"], activo=row["activo"], propietario=row["propietario"], ultimo_login=row["ultimo_login"],
    )


def _require_propietario(current_user: UserOut) -> None:
    if not current_user.propietario:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede gestionar usuarios"
        )


def _get_staff_or_404(conn, tenant_id: int, staff_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(STAFF_COLUMNS)} FROM usuarios "
        "WHERE id = :id AND (id = :tid OR propietario_id = :tid)",
        id=staff_id, tid=tenant_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return dict(zip(STAFF_COLUMNS, rows[0]))


@router.get("", response_model=list[UsuarioStaffOut])
def list_usuarios(tenant_id: int = Depends(get_tenant_id)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(STAFF_COLUMNS)} FROM usuarios "
            "WHERE id = :tid OR propietario_id = :tid ORDER BY propietario DESC, nombre",
            tid=tenant_id,
        )
        return [_row_to_staff(dict(zip(STAFF_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=UsuarioStaffOut, status_code=status.HTTP_201_CREATED)
def create_usuario(
    payload: UsuarioStaffIn,
    current_user: UserOut = Depends(get_current_user),
    tenant_id: int = Depends(get_tenant_id),
):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        password_hash = hash_password(payload.password)
        try:
            rows = conn.run(
                "INSERT INTO usuarios "
                "(username, nombre, email, password_hash, rol, activo, propietario, propietario_id) "
                "VALUES (:username, :nombre, :email, :password_hash, :rol, :activo, false, :tid) "
                f"RETURNING {', '.join(STAFF_COLUMNS)}",
                username=payload.username.strip(), nombre=payload.nombre.strip(), email=payload.email,
                password_hash=password_hash, rol=payload.rol, activo=payload.activo, tid=tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Ese usuario o correo ya está en uso"
                )
            raise
        return _row_to_staff(dict(zip(STAFF_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{staff_id}", response_model=UsuarioStaffOut)
def update_usuario(
    staff_id: int,
    payload: UsuarioStaffUpdateIn,
    current_user: UserOut = Depends(get_current_user),
    tenant_id: int = Depends(get_tenant_id),
):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        staff = _get_staff_or_404(conn, tenant_id, staff_id)
        if staff["propietario"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes editar al propietario")
        rows = conn.run(
            f"UPDATE usuarios SET nombre = :nombre, rol = :rol, activo = :activo "
            f"WHERE id = :id RETURNING {', '.join(STAFF_COLUMNS)}",
            id=staff_id, nombre=payload.nombre.strip(), rol=payload.rol, activo=payload.activo,
        )
        return _row_to_staff(dict(zip(STAFF_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{staff_id}/activo", response_model=UsuarioStaffOut)
def toggle_activo(
    staff_id: int,
    payload: UsuarioActivoIn,
    current_user: UserOut = Depends(get_current_user),
    tenant_id: int = Depends(get_tenant_id),
):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        staff = _get_staff_or_404(conn, tenant_id, staff_id)
        if staff["propietario"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes desactivar al propietario"
            )
        rows = conn.run(
            f"UPDATE usuarios SET activo = :activo WHERE id = :id RETURNING {', '.join(STAFF_COLUMNS)}",
            id=staff_id, activo=payload.activo,
        )
        return _row_to_staff(dict(zip(STAFF_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.post("/{staff_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    staff_id: int,
    payload: UsuarioResetPasswordIn,
    current_user: UserOut = Depends(get_current_user),
    tenant_id: int = Depends(get_tenant_id),
):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        staff = _get_staff_or_404(conn, tenant_id, staff_id)
        if staff["propietario"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No puedes restablecer la contraseña del propietario",
            )
        conn.run(
            "UPDATE usuarios SET password_hash = :ph WHERE id = :id",
            ph=hash_password(payload.password), id=staff_id,
        )
    finally:
        conn.close()


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_usuario(
    staff_id: int,
    current_user: UserOut = Depends(get_current_user),
    tenant_id: int = Depends(get_tenant_id),
):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        staff = _get_staff_or_404(conn, tenant_id, staff_id)
        if staff["propietario"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes eliminar al propietario")
        conn.run("DELETE FROM usuarios WHERE id = :id", id=staff_id)
    finally:
        conn.close()
