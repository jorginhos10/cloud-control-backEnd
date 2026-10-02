"""Búsqueda de direcciones para el pedido público: predicción al escribir, detalle de un lugar y dirección
a partir de coordenadas. Usa Google Maps cuando hay GOOGLE_MAPS_API_KEY; sin la llave, solo la dirección
a partir de coordenadas funciona (con OpenStreetMap) y la predicción queda desactivada."""
import base64
import json
import os
import re
import time

import httpx
from fastapi import HTTPException, Request, status

from app.geo import _client_ip
from app.tarifas_domicilio import NOMINATIM_URL, USER_AGENT, haversine_km

PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_DETAIL_URL = "https://places.googleapis.com/v1/places/"
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NOMINATIM_REVERSE_URL = NOMINATIM_URL.replace("/search", "/reverse")

PHOTON_URL = "https://photon.komoot.io/api/"
# Sin ubicación del negocio, la búsqueda se limita a Colombia (oeste, sur, este, norte).
BBOX_COLOMBIA = (-79.1, -4.3, -66.8, 13.5)

_hits: dict[str, list[float]] = {}

# Una sola conexión reutilizada: abrir una nueva (DNS + TLS) en cada letra tarda más que la búsqueda misma.
_cliente = httpx.Client(timeout=6, headers={"User-Agent": USER_AGENT})
# Las mismas búsquedas se repiten mucho (varios clientes, borrar y volver a escribir).
_cache_osm: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL_S = 600

# Tipo de vía abreviado como lo escribe la gente en Colombia -> como aparece en el mapa.
_TIPOS_VIA = {
    "cra": "Carrera", "cr": "Carrera", "kr": "Carrera", "k": "Carrera", "carr": "Carrera",
    "cl": "Calle", "cll": "Calle", "c": "Calle",
    "av": "Avenida", "avda": "Avenida", "ak": "Avenida Carrera", "ac": "Avenida Calle",
    "dg": "Diagonal", "diag": "Diagonal", "tv": "Transversal", "trans": "Transversal", "tr": "Transversal",
    "cir": "Circular", "autop": "Autopista",
}
_NUMERO_CASA = re.compile(r"(?:#|n[°ºo]\.?|nro\.?)\s*\d+\s*[a-z]?\s*[-–]?\s*\d*", re.IGNORECASE)


def google_key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def limitar(request: Request, clave: str, maximo: int, ventana_s: int = 60) -> None:
    """Freno por IP: estos endpoints son públicos y cada llamada a Google tiene costo."""
    ip = _client_ip(request) or "?"
    llave = f"{clave}:{ip}"
    ahora = time.monotonic()
    recientes = [t for t in _hits.get(llave, []) if ahora - t < ventana_s]
    if len(recientes) >= maximo:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Demasiadas búsquedas, intenta en un momento")
    recientes.append(ahora)
    _hits[llave] = recientes
    if len(_hits) > 5000:
        _hits.clear()


def _headers_google(field_mask: str | None = None) -> dict:
    h = {"X-Goog-Api-Key": google_key(), "Content-Type": "application/json"}
    if field_mask:
        h["X-Goog-FieldMask"] = field_mask
    return h


def _separar_via_y_numero(texto: str) -> tuple[str, str]:
    """"cra 51 # 45-20" -> ("Carrera 51", "# 45-20"): el mapa conoce la calle; el número lo agrega quien pide."""
    numero = ""
    m = _NUMERO_CASA.search(texto)
    if m:
        numero = re.sub(r"\s+", " ", m.group(0)).strip()
        texto = (texto[: m.start()] + " " + texto[m.end():]).strip()
    palabras = texto.split()
    if palabras:
        clave = palabras[0].lower().rstrip(".")
        if clave in _TIPOS_VIA and len(palabras) > 1:
            palabras[0] = _TIPOS_VIA[clave]
    return " ".join(palabras), numero


def _autocompletar_osm(texto: str, cerca: tuple[float, float] | None) -> list[dict]:
    """Predicción con Photon (datos de OpenStreetMap), pensado para buscar mientras se escribe."""
    via, numero = _separar_via_y_numero(texto)
    if len(via) < 3:
        return []
    params: dict = {"q": via, "limit": "8", "lang": "default"}
    if cerca:
        lat, lng = cerca
        params.update({"lat": str(lat), "lon": str(lng), "bbox": f"{lng - 0.5},{lat - 0.5},{lng + 0.5},{lat + 0.5}"})
    else:
        params["bbox"] = ",".join(str(v) for v in BBOX_COLOMBIA)
    clave_cache = json.dumps(params, sort_keys=True) + "|" + numero
    guardado = _cache_osm.get(clave_cache)
    if guardado and time.monotonic() - guardado[0] < CACHE_TTL_S:
        return guardado[1]

    rasgos = None
    for _ in range(2):  # el servicio público a veces tarda o rechaza una petición suelta: se reintenta una vez
        try:
            resp = _cliente.get(PHOTON_URL, params=params)
            resp.raise_for_status()
            rasgos = resp.json().get("features", [])
            break
        except (httpx.HTTPError, ValueError):
            continue
    if rasgos is None:
        return []
    pais = os.environ.get("GOOGLE_MAPS_REGION", "co").upper()

    salida, vistos = [], set()
    for f in rasgos:
        p = f.get("properties", {})
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) != 2:
            continue
        if p.get("countrycode") and p["countrycode"].upper() != pais:
            continue
        lng, lat = float(coords[0]), float(coords[1])
        calle = p.get("street") or p.get("name") or ""
        if not calle:
            continue
        casa = p.get("housenumber", "")
        principal = f"{calle} {casa}".strip() if p.get("type") == "house" and casa else calle
        if numero and not casa:
            principal = f"{principal} {numero}"
        barrio = re.sub(r"^Localidad\s+", "", p.get("suburb") or p.get("locality") or p.get("district") or "")
        ciudad = p.get("city") or p.get("county") or ""
        secundario = ", ".join(x for x in (barrio, ciudad, p.get("state", "")) if x)
        clave = (principal.lower(), secundario.lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        dato = {"d": principal, "b": barrio, "a": lat, "o": lng}
        ident = "osm:" + base64.urlsafe_b64encode(json.dumps(dato, ensure_ascii=False).encode()).decode()
        salida.append({
            "id": ident, "principal": principal, "secundario": secundario, "fuente": "osm",
            "distancia_km": round(haversine_km(cerca[0], cerca[1], lat, lng), 1) if cerca else None,
        })
    salida = salida[:6]
    if len(_cache_osm) > 500:
        _cache_osm.clear()
    _cache_osm[clave_cache] = (time.monotonic(), salida)
    return salida


def autocompletar(texto: str, sesion: str, cerca: tuple[float, float] | None) -> list[dict]:
    """Sugerencias de direcciones mientras el cliente escribe: Google Maps si hay llave, si no OpenStreetMap."""
    if not google_key():
        return _autocompletar_osm(texto, cerca)
    cuerpo: dict = {"input": texto, "languageCode": "es", "includedRegionCodes": [os.environ.get("GOOGLE_MAPS_REGION", "co")]}
    if sesion:
        cuerpo["sessionToken"] = sesion
    if cerca:
        centro = {"latitude": cerca[0], "longitude": cerca[1]}
        cuerpo["locationBias"] = {"circle": {"center": centro, "radius": 30000.0}}
        # Con el origen, Google devuelve la distancia en línea recta de cada sugerencia hasta el negocio.
        cuerpo["origin"] = centro
    try:
        resp = _cliente.post(PLACES_AUTOCOMPLETE_URL, json=cuerpo, headers=_headers_google())
        resp.raise_for_status()
        datos = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    salida = []
    for s in datos.get("suggestions", []):
        p = s.get("placePrediction")
        if not p or not p.get("placeId"):
            continue
        formato = p.get("structuredFormat", {})
        principal = formato.get("mainText", {}).get("text") or p.get("text", {}).get("text", "")
        secundario = formato.get("secondaryText", {}).get("text", "")
        metros = p.get("distanceMeters")
        salida.append({
            "id": p["placeId"], "principal": principal, "secundario": secundario,
            "distancia_km": round(metros / 1000, 1) if isinstance(metros, (int, float)) else None,
        })
    return salida[:6]


def _componente(componentes: list[dict], *tipos: str, clave: str = "longText") -> str:
    for tipo in tipos:
        for c in componentes:
            if tipo in c.get("types", []):
                return c.get(clave) or c.get("long_name") or ""
    return ""


def detalle_lugar(place_id: str, sesion: str) -> dict:
    """Dirección, barrio y coordenadas de una sugerencia elegida."""
    if place_id.startswith("osm:"):
        try:
            d = json.loads(base64.urlsafe_b64decode(place_id[4:].encode()))
            return {"direccion": str(d["d"])[:200], "barrio": str(d.get("b", ""))[:100], "lat": float(d["a"]), "lng": float(d["o"])}
        except (ValueError, KeyError, TypeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sugerencia no válida")
    if not google_key():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Búsqueda de direcciones no disponible")
    params = {"languageCode": "es"}
    if sesion:
        params["sessionToken"] = sesion
    try:
        resp = httpx.get(
            PLACES_DETAIL_URL + place_id, params=params, timeout=5,
            headers=_headers_google("location,formattedAddress,shortFormattedAddress,addressComponents"),
        )
        resp.raise_for_status()
        d = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo obtener el lugar")
    loc = d.get("location") or {}
    if "latitude" not in loc or "longitude" not in loc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo obtener el lugar")
    comps = d.get("addressComponents", [])
    barrio = _componente(comps, "neighborhood", "sublocality_level_1", "sublocality")
    direccion = d.get("shortFormattedAddress") or (d.get("formattedAddress", "").split(",")[0])
    return {"direccion": direccion, "barrio": barrio, "lat": loc["latitude"], "lng": loc["longitude"]}


def direccion_desde_coordenadas(lat: float, lng: float) -> dict:
    """Dirección y barrio de un punto (la ubicación del celular del cliente). Vacío si no se encuentra."""
    vacio = {"direccion": "", "barrio": "", "lat": lat, "lng": lng}
    try:
        if google_key():
            resp = httpx.get(GEOCODING_URL, params={"latlng": f"{lat},{lng}", "language": "es", "key": google_key()}, timeout=5)
            resp.raise_for_status()
            resultados = resp.json().get("results", [])
            if not resultados:
                return vacio
            # El primero suele ser la dirección exacta; si no trae calle, se toma el primero que sí la tenga.
            elegido = next((r for r in resultados if any("route" in c.get("types", []) for c in r.get("address_components", []))), resultados[0])
            comps = elegido.get("address_components", [])
            barrio = _componente(comps, "neighborhood", "sublocality_level_1", "sublocality", clave="long_name")
            direccion = elegido.get("formatted_address", "").split(",")[0]
            return {"direccion": direccion, "barrio": barrio, "lat": lat, "lng": lng}

        resp = httpx.get(
            NOMINATIM_REVERSE_URL,
            params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1, "accept-language": "es", "zoom": 18},
            headers={"User-Agent": USER_AGENT}, timeout=5,
        )
        resp.raise_for_status()
        a = resp.json().get("address", {})
        via = " ".join(p for p in (a.get("road", ""), a.get("house_number", "")) if p)
        barrio = a.get("neighbourhood") or a.get("suburb") or a.get("quarter") or ""
        return {"direccion": via, "barrio": barrio, "lat": lat, "lng": lng}
    except (httpx.HTTPError, ValueError):
        return vacio
