"""Cálculo del valor del domicilio según la configuración del negocio (gratis, personalizado o automático)."""
import math

import httpx

from app.schemas import DomicilioCotizacionOut

USER_AGENT = "ChefControl/1.0 (domicilios)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
# Si el servicio de rutas no responde, la distancia en línea recta se multiplica por este factor
# para aproximar el recorrido real por las calles.
FACTOR_VIA = 1.3

_cache_geocodificacion: dict[str, tuple[float, float]] = {}

CONFIG_COLUMNS = ["modo", "valor_fijo", "tarifa_base", "km_base", "valor_km", "radio_max_km", "lat", "lng"]


def cargar_config(conn, usuario_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(CONFIG_COLUMNS)} FROM domicilio_config WHERE usuario_id = :uid", uid=usuario_id
    )
    if not rows:
        return {
            "modo": "personalizado", "valor_fijo": None, "tarifa_base": 0.0, "km_base": 2.0,
            "valor_km": 0.0, "radio_max_km": None, "lat": None, "lng": None,
        }
    cfg = dict(zip(CONFIG_COLUMNS, rows[0]))
    for k in ("valor_fijo", "tarifa_base", "km_base", "valor_km", "radio_max_km"):
        if cfg[k] is not None:
            cfg[k] = float(cfg[k])
    return cfg


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocodificar(consulta: str, cerca: tuple[float, float] | None = None) -> tuple[float, float] | None:
    """Coordenadas de una dirección con OpenStreetMap (Nominatim). None si no la encuentra o no hay red."""
    consulta = consulta.strip()
    if not consulta:
        return None
    clave = f"{consulta.lower()}|{cerca}"
    if clave in _cache_geocodificacion:
        return _cache_geocodificacion[clave]

    params = {"q": consulta, "format": "json", "limit": "1"}
    if cerca:
        lat, lng = cerca
        # Limita la búsqueda a unos 45 km alrededor del negocio para no confundir direcciones de otras ciudades.
        params["viewbox"] = f"{lng - 0.4},{lat + 0.4},{lng + 0.4},{lat - 0.4}"
        params["bounded"] = "1"
    try:
        resp = httpx.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=5)
        resp.raise_for_status()
        datos = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not datos:
        return None
    resultado = (float(datos[0]["lat"]), float(datos[0]["lon"]))
    if len(_cache_geocodificacion) > 1000:
        _cache_geocodificacion.clear()
    _cache_geocodificacion[clave] = resultado
    return resultado


def distancia_km(origen: tuple[float, float], destino: tuple[float, float]) -> float:
    try:
        url = f"{OSRM_URL}/{origen[1]},{origen[0]};{destino[1]},{destino[0]}"
        resp = httpx.get(url, params={"overview": "false"}, headers={"User-Agent": USER_AGENT}, timeout=5)
        resp.raise_for_status()
        return float(resp.json()["routes"][0]["distance"]) / 1000
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return haversine_km(*origen, *destino) * FACTOR_VIA


def _redondear(valor: float) -> float:
    # Los valores en pesos se redondean a la centena; con monedas de decimales se dejan en centavos.
    return float(round(valor / 100) * 100) if valor >= 1000 else round(valor, 2)


def _ciudad_del_negocio(conn, usuario_id: int) -> str:
    rows = conn.run("SELECT ciudad FROM negocios WHERE usuario_id = :uid", uid=usuario_id)
    return (rows[0][0] or "").strip() if rows else ""


def cotizar(
    conn, usuario_id: int, tipo: str, direccion: str, barrio: str, lat: float | None, lng: float | None
) -> DomicilioCotizacionOut:
    cfg = cargar_config(conn, usuario_id)
    modo = cfg["modo"]
    if tipo != "domicilio":
        return DomicilioCotizacionOut(modo=modo)

    if modo == "gratis":
        return DomicilioCotizacionOut(modo=modo, valor=0, mensaje="Domicilio gratis")

    if modo == "personalizado":
        valor = cfg["valor_fijo"] or None
        return DomicilioCotizacionOut(
            modo=modo, valor=valor,
            mensaje="" if valor is not None else "El negocio te confirmará el valor del domicilio.",
        )

    negocio = (cfg["lat"], cfg["lng"]) if cfg["lat"] is not None and cfg["lng"] is not None else None
    if negocio is None:
        return DomicilioCotizacionOut(modo=modo, mensaje="El negocio te confirmará el valor del domicilio.")

    cliente = (lat, lng) if lat is not None and lng is not None else None
    if cliente is None:
        partes = [p for p in (direccion.strip(), barrio.strip(), _ciudad_del_negocio(conn, usuario_id)) if p]
        cliente = geocodificar(", ".join(partes), cerca=negocio) if direccion.strip() else None
    if cliente is None:
        return DomicilioCotizacionOut(
            modo=modo,
            mensaje="No pudimos ubicar tu dirección. Usa tu ubicación actual o el negocio te confirmará el valor.",
        )

    km = round(distancia_km(negocio, cliente), 1)
    if cfg["radio_max_km"] is not None and km > cfg["radio_max_km"]:
        return DomicilioCotizacionOut(
            modo=modo, distancia_km=km, fuera_de_cobertura=True,
            mensaje=f"Tu dirección está a {km} km y el negocio entrega hasta {cfg['radio_max_km']:g} km.",
        )
    extra = max(0.0, km - cfg["km_base"])
    valor = _redondear(cfg["tarifa_base"] + extra * cfg["valor_km"])
    return DomicilioCotizacionOut(modo=modo, valor=valor, distancia_km=km, mensaje=f"Distancia aproximada: {km} km")
