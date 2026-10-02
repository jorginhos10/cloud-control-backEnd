"""Plan-based access to modules.

The SuperAdmin picks which modules each plan includes (planes.modulos). A comercio can only use
the modules of its plan: this file maps the API routes of every module to its slug(s) and a
global guard rejects any request to a module route the account's plan doesn't include.

Routes that are not listed here (auth, dashboard, negocio, configuracion, usuarios, suscripcion,
facturacion-electronica, onboarding and the public pages) are always available.
"""
import json
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import get_current_user, get_current_user_any_status
from app.database import get_connection, get_superadmin_connection

MODULO_NO_INCLUIDO_DETAIL = "Tu plan no incluye este módulo"

# Route prefix -> module slug(s); any of the slugs grants access. The most specific prefix wins.
# An optional third item limits the rule to those HTTP methods (other methods fall to a broader rule).
# Keep in sync with RUTA_MODULOS in the client (core/modulos/modulos.service.ts).
RUTAS_MODULO: list[tuple] = [
    ("/ventas/mis-propinas", ("propinas",)),
    ("/ventas", ("ventas",)),
    ("/salon", ("mesas",)),
    ("/mesas", ("mesas",)),
    ("/zonas", ("mesas",)),
    ("/cocina", ("cocina",)),
    ("/menu-digital", ("menu-digital",)),
    ("/domicilios", ("domicilios",)),
    ("/clientes", ("clientes",)),
    ("/cupones", ("cupones",)),
    ("/pqrs", ("pqrs",)),
    # The sales screens (mesa, venta directa) read the recipe categories to filter the catalog,
    # so reading them is allowed with Ventas too; changing them still needs Recetas.
    ("/recetas/categorias", ("recetas", "ventas"), ("GET",)),
    ("/recetas", ("recetas",)),
    ("/insumos", ("insumos", "inventario")),
    ("/activos-fijos", ("inventario-inmobiliario",)),
    ("/proveedores", ("proveedores",)),
    ("/ingresos", ("ingresos",)),
    ("/perdidas", ("perdidas",)),
    ("/reportes", ("reportes",)),
    ("/chat-soporte", ("chat",)),
    ("/soporte", ("soporte",)),  # support tickets (Wallet has no API, it is only a screen)
    ("/marketplace", ("marketplace",)),
    ("/nomina", ("nomina",)),
]

_TTL_SEGUNDOS = 10
_cache_planes: dict[int, tuple[float, frozenset[str]]] = {}
_bearer = HTTPBearer(auto_error=False)


def modulos_requeridos(path: str, method: str = "GET") -> tuple[str, ...] | None:
    """Slugs that grant access to `path`, or None when the path belongs to no module."""
    mejor: tuple[str, tuple[str, ...]] | None = None
    for prefijo, slugs, *metodos in RUTAS_MODULO:
        if metodos and method.upper() not in metodos[0]:
            continue
        if path == prefijo or path.startswith(prefijo + "/"):
            if mejor is None or len(prefijo) > len(mejor[0]):
                mejor = (prefijo, slugs)
    return mejor[1] if mejor else None


def _modulos_del_plan(plan_id: int) -> frozenset[str]:
    ahora = time.monotonic()
    guardado = _cache_planes.get(plan_id)
    if guardado and guardado[0] > ahora:
        return guardado[1]
    try:
        sconn = get_superadmin_connection()
        try:
            filas = sconn.run("SELECT modulos FROM planes WHERE id = :id", id=plan_id)
        finally:
            sconn.close()
    except Exception:
        # The SuperAdmin database being briefly unreachable shouldn't take every comercio down:
        # keep serving the last known answer; with none, refuse rather than open everything.
        if guardado:
            return guardado[1]
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No se pudo verificar tu plan")
    modulos = filas[0][0] if filas else []
    if isinstance(modulos, str):
        modulos = json.loads(modulos)
    resultado = frozenset(modulos or [])
    _cache_planes[plan_id] = (ahora + _TTL_SEGUNDOS, resultado)
    return resultado


def modulos_de_cuenta(tenant_id: int) -> frozenset[str]:
    """Modules the account's plan includes. No plan means no modules."""
    conn = get_connection()
    try:
        filas = conn.run("SELECT plan_id FROM usuarios WHERE id = :id", id=tenant_id)
    finally:
        conn.close()
    plan_id = filas[0][0] if filas else None
    return _modulos_del_plan(plan_id) if plan_id is not None else frozenset()


def guardia_de_modulos(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """App-wide dependency: blocks module routes the account's plan doesn't include."""
    requeridos = modulos_requeridos(request.url.path, request.method)
    if requeridos is None or request.method == "OPTIONS" or credentials is None:
        # Not a module route (or no credentials: the route's own auth answers 401 as usual).
        return
    # Same checks the routes make (valid token, active and approved account).
    usuario = get_current_user(get_current_user_any_status(credentials))
    if not set(requeridos) & modulos_de_cuenta(usuario.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MODULO_NO_INCLUIDO_DETAIL)
