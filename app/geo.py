import ipaddress

import httpx
from fastapi import Request


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


def detectar_pais(request: Request) -> str | None:
    """Best-effort geolocation by IP — never raises. Returns an ISO-3166
    alpha-2 country code (e.g. "CO"), or None when it can't be determined
    (local/private IPs, the geolocation service being unreachable, etc.)."""
    ip = _client_ip(request)
    if not ip or _es_ip_privada(ip):
        return None

    try:
        resp = httpx.get(f"https://ipapi.co/{ip}/json/", timeout=4)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except httpx.RequestError:
        return None
    except ValueError:
        return None

    codigo = data.get("country_code")
    return codigo.upper() if codigo and len(codigo) == 2 else None
