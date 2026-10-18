import ipaddress
import logging

import httpx
from fastapi import Request

logger = logging.getLogger("geo")


def _client_ip(request: Request) -> str | None:
    """Real client IP even behind nginx — X-Forwarded-For wins when present."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _es_ip_privada(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


# Servicios gratuitos de geolocalización por IP, en orden de preferencia. Antes se usaba solo
# ipapi.co, que responde 429 (RateLimited) a las IPs de AWS: la detección fallaba siempre y todas
# las cuentas quedaban con pais NULL (SuperAdmin las mostraba como "Colombia" por el plan por
# defecto, incluso las de otros países). Con varios proveedores, uno que falle no deja el campo vacío.
_PROVEEDORES = [
    ("https://api.country.is/{ip}", lambda d: d.get("country")),
    ("https://get.geojs.io/v1/ip/country/{ip}.json", lambda d: d.get("country")),
    ("https://ipwho.is/{ip}", lambda d: d.get("country_code") if d.get("success", True) else None),
]
_TIMEOUT_S = 2.0


def _consultar(url: str, extraer) -> str | None:
    try:
        resp = httpx.get(url, timeout=_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        codigo = extraer(resp.json())
    except (httpx.RequestError, ValueError):
        return None
    if isinstance(codigo, str) and len(codigo) == 2 and codigo.isalpha():
        return codigo.upper()
    return None


def detectar_pais(request: Request) -> str | None:
    """Best-effort geolocation by IP — never raises. Returns an ISO-3166
    alpha-2 country code (e.g. "CO"), or None when it can't be determined
    (local/private IPs, every geolocation service being unreachable, etc.)."""
    ip = _client_ip(request)
    if not ip or _es_ip_privada(ip):
        return None

    for plantilla, extraer in _PROVEEDORES:
        codigo = _consultar(plantilla.format(ip=ip), extraer)
        if codigo:
            return codigo

    logger.warning("No se pudo detectar el país de la IP %s con ningún proveedor", ip)
    return None
