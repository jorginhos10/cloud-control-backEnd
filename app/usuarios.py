from fastapi import APIRouter, Depends, HTTPException, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, _invalidar_cache_usuario, _make_username, get_current_user, get_tenant_id
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

STAFF_COLUMNS = [
    "id", "username", "nombre", "apellido", "telefono", "email", "numero_documento",
    "rol", "activo", "propietario", "ultimo_login",
]


def _row_to_staff(row: dict, categoria_ids: list[int] | None = None) -> UsuarioStaffOut:
    return UsuarioStaffOut(
        id=row["id"], username=row["username"], nombre=row["nombre"], apellido=row["apellido"],
        telefono=row["telefono"], email=row["email"], numero_documento=row["numero_documento"],
        rol=row["rol"], activo=row["activo"], propietario=row["propietario"], ultimo_login=row["ultimo_login"],
        categoria_ids=categoria_ids or [],
    )


def _categoria_ids_de(conn, usuario_id: int) -> list[int]:
    rows = conn.run("SELECT categoria_id FROM usuario_categorias WHERE usuario_id = :id", id=usuario_id)
    return [r[0] for r in rows]


def _set_categoria_ids(conn, tenant_id: int, usuario_id: int, categoria_ids: list[int]) -> None:
    """Reemplaza las categorías asignadas, validando que cada una sea del mismo negocio —
    así una petición manipulada no puede engancharse a la categoría de otro tenant."""
    conn.run("DELETE FROM usuario_categorias WHERE usuario_id = :id", id=usuario_id)
    for categoria_id in set(categoria_ids):
        existe = conn.run(
            "SELECT 1 FROM receta_categorias WHERE id = :id AND usuario_id = :uid",
            id=categoria_id, uid=tenant_id,
        )
        if not existe:
            continue
        conn.run(
            "INSERT INTO usuario_categorias (usuario_id, categoria_id) VALUES (:uid, :cid)",
            uid=usuario_id, cid=categoria_id,
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
def list_usuarios(current_user: UserOut = Depends(get_current_user), tenant_id: int = Depends(get_tenant_id)):
    # numero_documento viaja en esta respuesta y es la contraseña inicial de cada cuenta —
    # solo el propietario puede verla, igual que ya exigían todos los demás endpoints de este router.
    _require_propietario(current_user)
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(STAFF_COLUMNS)} FROM usuarios "
            "WHERE id = :tid OR propietario_id = :tid ORDER BY propietario DESC, nombre",
            tid=tenant_id,
        )
        staff = [dict(zip(STAFF_COLUMNS, r)) for r in rows]
        return [_row_to_staff(s, _categoria_ids_de(conn, s["id"])) for s in staff]
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
        username = _make_username(conn, payload.email)
        password_hash = hash_password(payload.numero_documento.strip())
        try:
            rows = conn.run(
                "INSERT INTO usuarios "
                "(username, nombre, apellido, telefono, email, numero_documento, password_hash, "
                "rol, activo, propietario, propietario_id) "
                "VALUES (:username, :nombre, :apellido, :telefono, :email, :numero_documento, :password_hash, "
                ":rol, :activo, false, :tid) "
                f"RETURNING {', '.join(STAFF_COLUMNS)}",
                username=username, nombre=payload.nombre.strip(), apellido=payload.apellido.strip(),
                telefono=payload.telefono.strip(), email=payload.email,
                numero_documento=payload.numero_documento.strip(),
                password_hash=password_hash, rol=payload.rol, activo=payload.activo, tid=tenant_id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Ese usuario o correo ya está en uso"
                )
            raise
        nuevo = dict(zip(STAFF_COLUMNS, rows[0]))
        _set_categoria_ids(conn, tenant_id, nuevo["id"], payload.categoria_ids)
        return _row_to_staff(nuevo, _categoria_ids_de(conn, nuevo["id"]))
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
            f"UPDATE usuarios SET nombre = :nombre, apellido = :apellido, telefono = :telefono, "
            f"numero_documento = :numero_documento, rol = :rol, activo = :activo "
            f"WHERE id = :id RETURNING {', '.join(STAFF_COLUMNS)}",
            id=staff_id, nombre=payload.nombre.strip(), apellido=payload.apellido.strip(),
            telefono=payload.telefono.strip(), numero_documento=payload.numero_documento.strip(),
            rol=payload.rol, activo=payload.activo,
        )
        _set_categoria_ids(conn, tenant_id, staff_id, payload.categoria_ids)
        return _row_to_staff(dict(zip(STAFF_COLUMNS, rows[0])), _categoria_ids_de(conn, staff_id))
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
        # Si se desactivó, que no le sirvan las peticiones que ya tenía en camino con la sesión en caché.
        if not payload.activo:
            _invalidar_cache_usuario(staff_id)
        return _row_to_staff(dict(zip(STAFF_COLUMNS, rows[0])), _categoria_ids_de(conn, staff_id))
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
