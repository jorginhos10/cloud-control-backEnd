import os
import re
import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pg8000.exceptions import DatabaseError

from app import geo
from app.database import get_connection, get_superadmin_connection
from app.schemas import CambiarPasswordIn, ImpersonateIn, LoginIn, PerfilUpdateIn, RegisterIn, TokenOut, UserOut
from app.security import JWT_EXPIRE_MINUTES, create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()

UNIQUE_VIOLATION = "23505"

# La app de domiciliarios no tiene refresh token; sesiones cortas ahí solo logran que el
# repartidor tenga que relogearse a mitad de turno. 30 días es normal para un rol de un solo
# propósito en un celular propio — el resto de roles (web) se queda con JWT_EXPIRE_MINUTES.
DOMICILIARIO_JWT_EXPIRE_MINUTES = 60 * 24 * 30

USER_COLUMNS = [
    "id", "username", "nombre", "email", "rol", "activo", "propietario", "ultimo_login", "propietario_id",
    "fecha_creacion", "estado_aprobacion", "motivo_rechazo",
]

CUENTA_PENDIENTE_DETAIL = "Tu cuenta está pendiente de aprobación"

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
        estado_aprobacion=row["estado_aprobacion"],
        motivo_rechazo=row["motivo_rechazo"],
    )


def _asignar_plan_predeterminado(conn, usuario_id: int, pais: str | None) -> None:
    """Best-effort: new signups get whichever plan the SuperAdmin marked as
    automatic for their country (falling back to any país's default plan if
    theirs has none configured yet). Never blocks registration if the
    SuperAdmin database is down — the restaurant just ends up without a
    plan, settable later from Suscripción."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return
    try:
        rows = []
        if pais:
            rows = sconn.run(
                "SELECT id FROM planes WHERE predeterminado = true AND activo = true AND pais = :pais LIMIT 1",
                pais=pais,
            )
        if not rows:
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
def register(payload: RegisterIn, request: Request):
    pais = geo.detectar_pais(request)

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
                INSERT INTO usuarios (username, nombre, email, password_hash, rol, activo, propietario, pais,
                                      estado_aprobacion)
                VALUES (:username, :nombre, :email, :password_hash, 'admin', true, true, :pais, 'pendiente_datos')
                RETURNING {", ".join(USER_COLUMNS)}
                """,
                username=username,
                nombre=payload.full_name,
                email=payload.email,
                password_hash=password_hash,
                pais=pais,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")
            raise

        user = _row_to_user(dict(zip(USER_COLUMNS, rows[0])))
        _seed_entorno_inicial(conn, user.id)
        _asignar_plan_predeterminado(conn, user.id, pais)
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
        # La app de domiciliarios no tiene refresco de sesión: si el token se vence a mitad de
        # turno, el repartidor ve "token inválido" en cada pantalla hasta que alguien le explica
        # que tiene que cerrar sesión y volver a entrar. Un token de más duración para ese rol
        # evita el problema de raíz en vez de solo maquillarlo.
        expire_minutes = DOMICILIARIO_JWT_EXPIRE_MINUTES if user.rol == "domiciliario" else JWT_EXPIRE_MINUTES
        token = create_access_token(user_id=user.id, email=user.email, expire_minutes=expire_minutes)
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


# Una ráfaga de peticiones con el mismo token (el dashboard pidiendo varios paneles a la vez, o el
# sondeo de Cocina/Domicilios cada pocos segundos) no necesita repetir la consulta del usuario en
# cada una — se reutiliza por unos segundos. El TTL es corto a propósito: una cuenta que se
# desactiva a mitad de camino deja de pasar casi de inmediato, no en la próxima hora.
_SESSION_CACHE_TTL_S = float(os.environ.get("SESSION_CACHE_TTL_S", "4"))
_session_cache: dict[str, tuple[float, UserOut]] = {}
_session_cache_lock = threading.Lock()


def _invalidar_cache_usuario(user_id: int) -> None:
    """Se llama tras cambiar datos propios del usuario (perfil, aprobación) para que el cambio se
    vea de inmediato y no haya que esperar a que expire la caché."""
    with _session_cache_lock:
        for clave in [c for c, (_, u) in _session_cache.items() if u.id == user_id]:
            del _session_cache[clave]


def get_current_user_any_status(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> UserOut:
    """Authenticates without requiring the account to be approved — only for the
    endpoints a not-yet-approved owner needs (/auth/me and /onboarding). Everything
    else goes through get_current_user."""
    token = credentials.credentials
    now = time.monotonic()

    cached = _session_cache.get(token)
    if cached and cached[0] > now:
        return cached[1]

    try:
        payload = decode_access_token(token)
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
        user = _row_to_user(row)
    finally:
        conn.close()

    with _session_cache_lock:
        if len(_session_cache) > 2000:
            _session_cache.clear()
        _session_cache[token] = (now + _SESSION_CACHE_TTL_S, user)
    return user


def get_current_user(user: UserOut = Depends(get_current_user_any_status)) -> UserOut:
    if user.estado_aprobacion != "aprobado":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CUENTA_PENDIENTE_DETAIL)
    return user


@router.get("/me", response_model=UserOut)
def me(current_user: UserOut = Depends(get_current_user_any_status)):
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


def require_roles(*roles: str):
    """Guardia para endpoints que solo el propietario o el personal con alguno de estos
    `rol` puede usar (ej. nómina, reportes, ajustes del negocio). El propietario siempre
    pasa sin importar su `rol`. Antes de esto, el rol del staff (mesero/cocina/inventario)
    solo se filtraba en el frontend — cualquier cuenta con token válido podía llamar
    estos endpoints igual; esto cierra esa puerta del lado del servidor."""

    def checker(current_user: UserOut = Depends(get_current_user)) -> UserOut:
        if current_user.propietario or current_user.rol in roles:
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para esto")

    return checker


def get_tenant_id(current_user: UserOut = Depends(get_current_user)) -> int:
    """Resolves the effective tenant/environment id for the logged-in account.

    Staff accounts (propietario_id set) share their owner's data; owner accounts
    are their own tenant. Every data router scopes queries by this, not by the
    raw login id, so a restaurant's staff logins all see the same environment.
    """
    return current_user.tenant_id
