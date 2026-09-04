import os
import re

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pg8000.exceptions import DatabaseError

from app.database import get_connection, get_superadmin_connection
from app.schemas import CambiarPasswordIn, ImpersonateIn, LoginIn, PerfilUpdateIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()

UNIQUE_VIOLATION = "23505"

USER_COLUMNS = [
    "id", "username", "nombre", "email", "rol", "activo", "propietario", "ultimo_login", "propietario_id",
    "fecha_creacion",
]

DEFAULT_CATEGORIAS = [
    ("entrada", "Entrada", 1),
    ("plato_fuerte", "Plato fuerte", 2),
    ("postre", "Postre", 3),
    ("bebida", "Bebida", 4),
    ("snack", "Snack", 5),
    ("otro", "Otro", 6),
]


def _seed_entorno_inicial(conn, usuario_id: int) -> None:
    conn.run(
        "INSERT INTO zonas (usuario_id, key, label, orden) VALUES (:uid, 'otro', 'Otro', 1)",
        uid=usuario_id,
    )
    for key, label, orden in DEFAULT_CATEGORIAS:
        conn.run(
            "INSERT INTO receta_categorias (usuario_id, key, label, orden) VALUES (:uid, :key, :label, :orden)",
            uid=usuario_id, key=key, label=label, orden=orden,
        )


def _row_to_user(row: dict) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        nombre=row["nombre"],
        email=row["email"],
        rol=row["rol"],
        activo=row["activo"],
        propietario=row["propietario"],
        ultimo_login=row["ultimo_login"],
        propietario_id=row["propietario_id"],
        tenant_id=row["propietario_id"] or row["id"],
        fecha_creacion=row["fecha_creacion"],
    )


def _asignar_plan_predeterminado(conn, usuario_id: int) -> None:
    """Best-effort: new signups get whichever plan the SuperAdmin marked as
    automatic. Never blocks registration if the SuperAdmin database is down —
    the restaurant just ends up without a plan, settable later from Suscripción."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return
    try:
        rows = sconn.run("SELECT id FROM planes WHERE predeterminado = true AND activo = true LIMIT 1")
        if not rows:
            return
        plan_id = rows[0][0]
    finally:
        sconn.close()

    conn.run(
        "UPDATE usuarios SET plan_id = :pid, plan_actualizado_en = now() WHERE id = :id",
        pid=plan_id, id=usuario_id,
    )


def _make_username(conn, email: str) -> str:
    base = re.sub(r"[^a-z0-9.]", "", email.split("@")[0].lower()) or "usuario"
    base = base[:45]
    candidate = base
    suffix = 1
    while conn.run("SELECT 1 FROM usuarios WHERE username = :u", u=candidate):
        suffix += 1
        candidate = f"{base}{suffix}"[:50]
    return candidate


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn):
    conn = get_connection()
    try:
        existing = conn.run("SELECT 1 FROM usuarios WHERE email = :e", e=payload.email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")

        username = _make_username(conn, payload.email)
        password_hash = hash_password(payload.password)

        try:
            rows = conn.run(
                f"""
                INSERT INTO usuarios (username, nombre, email, password_hash, rol, activo, propietario)
                VALUES (:username, :nombre, :email, :password_hash, 'admin', true, true)
                RETURNING {", ".join(USER_COLUMNS)}
                """,
                username=username,
                nombre=payload.full_name,
                email=payload.email,
                password_hash=password_hash,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")
            raise

        user = _row_to_user(dict(zip(USER_COLUMNS, rows[0])))
        _seed_entorno_inicial(conn, user.id)
        _asignar_plan_predeterminado(conn, user.id)
        token = create_access_token(user_id=user.id, email=user.email)
        return TokenOut(access_token=token, user=user)
    finally:
        conn.close()


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn):
    identificador = payload.email.strip()
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(USER_COLUMNS)}, password_hash FROM usuarios "
            "WHERE email = :e OR numero_documento = :e",
            e=identificador,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        row = dict(zip(USER_COLUMNS + ["password_hash"], rows[0]))

        if not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        if not row["activo"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta desactivada")

        updated = conn.run(
            f"UPDATE usuarios SET ultimo_login = now() WHERE id = :id RETURNING {', '.join(USER_COLUMNS)}",
            id=row["id"],
        )
        user = _row_to_user(dict(zip(USER_COLUMNS, updated[0])))
        token = create_access_token(user_id=user.id, email=user.email)
        return TokenOut(access_token=token, user=user)
    finally:
        conn.close()


@router.post("/impersonate", response_model=TokenOut)
def impersonate(payload: ImpersonateIn, x_service_secret: str = Header(default="")):
    """Server-to-server only: mints a login token for a restaurant owner without
    their password. Called by the SuperAdmin backend's "enter as" action, never
    reachable from a browser directly — gated by a shared secret, not a user
    session."""
    expected = os.environ.get("SUPERADMIN_SERVICE_SECRET", "")
    if not expected or x_service_secret != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(USER_COLUMNS)} FROM usuarios WHERE id = :id AND propietario = true",
            id=payload.user_id,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")

        user = _row_to_user(dict(zip(USER_COLUMNS, rows[0])))
        token = create_access_token(user_id=user.id, email=user.email)
        return TokenOut(access_token=token, user=user)
    finally:
        conn.close()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> UserOut:
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(USER_COLUMNS)} FROM usuarios WHERE id = :id",
            id=int(payload["sub"]),
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
        row = dict(zip(USER_COLUMNS, rows[0]))
        if not row["activo"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta desactivada")
        return _row_to_user(row)
    finally:
        conn.close()


@router.get("/me", response_model=UserOut)
def me(current_user: UserOut = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
def actualizar_perfil(payload: PerfilUpdateIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        try:
            rows = conn.run(
                f"UPDATE usuarios SET nombre = :nombre, email = :email WHERE id = :id "
                f"RETURNING {', '.join(USER_COLUMNS)}",
                nombre=payload.nombre.strip(), email=payload.email, id=current_user.id,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")
            raise
        return _row_to_user(dict(zip(USER_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_password(payload: CambiarPasswordIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run("SELECT password_hash FROM usuarios WHERE id = :id", id=current_user.id)
        if not verify_password(payload.actual, rows[0][0]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta")
        conn.run(
            "UPDATE usuarios SET password_hash = :hash WHERE id = :id",
            hash=hash_password(payload.nueva), id=current_user.id,
        )
    finally:
        conn.close()


def get_tenant_id(current_user: UserOut = Depends(get_current_user)) -> int:
    """Resolves the effective tenant/environment id for the logged-in account.

    Staff accounts (propietario_id set) share their owner's data; owner accounts
    are their own tenant. Every data router scopes queries by this, not by the
    raw login id, so a restaurant's staff logins all see the same environment.
    """
    return current_user.tenant_id
