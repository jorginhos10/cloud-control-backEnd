"""Envío de SMS y verificación del teléfono con un código de 4 dígitos.

La conexión con el proveedor de SMS (dirección de la API, credenciales, formato del cuerpo) se administra
desde el panel SuperAdmin (Mensajería › tuerca) y se guarda en la tabla sms_config de su base de datos.
Mientras no esté activada, la verificación queda apagada y el registro funciona como siempre: así nadie
se queda sin poder registrarse por un servicio que todavía no está conectado.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.database import get_superadmin_connection

logger = logging.getLogger("sms")

CODIGO_VIGENCIA_MIN = 10
MAX_INTENTOS = 5
REENVIO_ESPERA_S = 180
MAX_ENVIOS_POR_HORA = 5


class SmsNoConfigurado(Exception):
    """No hay proveedor de SMS configurado."""


class SmsFallo(Exception):
    """El proveedor rechazó o no pudo entregar el mensaje."""


CONFIG_COLUMNAS = [
    "proveedor", "activo", "url", "metodo", "auth_tipo", "auth_usuario", "auth_secreto", "auth_header_nombre",
    "remitente", "content_type", "cuerpo_plantilla", "exito_contiene",
]
_CACHE_S = 15
_cache: dict = {"t": 0.0, "cfg": None}


def _config() -> dict | None:
    """Configuración del proveedor (se relee cada 15 s para que un cambio del SuperAdmin se aplique pronto)."""
    ahora = time.time()
    if ahora - _cache["t"] < _CACHE_S:
        return _cache["cfg"]
    cfg = None
    try:
        sconn = get_superadmin_connection()
        try:
            rows = sconn.run(f"SELECT {', '.join(CONFIG_COLUMNAS)} FROM sms_config WHERE id = 1")
            if rows:
                cfg = dict(zip(CONFIG_COLUMNAS, rows[0]))
                # Países con el interruptor encendido en el mapa de Mensajería: solo ellos piden el código.
                regiones = sconn.run("SELECT codigo_pais, sms_verificacion, activo, indicativo FROM regiones")
                cfg["paises"] = {r[0].upper() for r in regiones if r[1] and r[2]}
                cfg["indicativos"] = {r[0].upper(): r[3] for r in regiones if r[3]}
        finally:
            sconn.close()
    except Exception:
        logger.warning("No se pudo leer la configuración de SMS", exc_info=True)
    _cache.update(t=ahora, cfg=cfg)
    return cfg


def proveedor() -> str:
    cfg = _config()
    return (cfg["proveedor"] if cfg else "") or ""


def sms_configurado() -> bool:
    cfg = _config()
    return bool(cfg and cfg["activo"] and cfg["url"])


def verificacion_requerida(pais: str | None) -> bool:
    """Hay proveedor conectado Y el país de la cuenta está encendido en el mapa de países."""
    cfg = _config()
    return bool(sms_configurado() and cfg and (pais or "CO").upper() in cfg.get("paises", set()))


def solo_digitos(telefono: str) -> str:
    return re.sub(r"\D", "", telefono or "")


def a_internacional(telefono: str, pais: str | None) -> str:
    """Dígitos con indicativo de país, que es lo que piden los proveedores (57300… para Colombia).

    El indicativo sale de la región (Regiones › Indicativo). Si la persona ya lo escribió, se respeta;
    si escribió solo el número local, se le antepone.
    """
    d = solo_digitos(telefono)
    if d.startswith("00"):
        d = d[2:]
    codigo = (pais or "CO").upper()
    cfg = _config() or {}
    ind = (cfg.get("indicativos") or {}).get(codigo) or ("57" if codigo == "CO" else "")
    if not ind:
        return d
    if d.startswith(ind) and len(d) >= len(ind) + 7:
        return d
    return ind + d.lstrip("0")


def _hash_codigo(usuario_id: int, codigo: str) -> str:
    secreto = os.environ.get("JWT_SECRET", "violet").encode()
    return hmac.new(secreto, f"{usuario_id}:{codigo}".encode(), hashlib.sha256).hexdigest()


def generar_codigo() -> str:
    """4 dígitos, fáciles de teclear; se descartan los que son todos iguales (0000, 7777…)."""
    while True:
        codigo = f"{secrets.randbelow(10000):04d}"
        if len(set(codigo)) > 1:
            return codigo


_PATRON = re.compile(r"\{(telefono|mensaje|remitente|usuario)\}")
_TIMEOUT_S = 15.0
SIN_CONFIRMACION = "sin_confirmacion"


def _cuerpo_json(plantilla: str, valores: dict) -> str:
    # Cada valor se escapa como texto JSON, así un mensaje con comillas o saltos de línea no rompe el cuerpo.
    return _PATRON.sub(lambda m: json.dumps(valores[m.group(1)], ensure_ascii=False)[1:-1], plantilla)


def _campos_form(plantilla: str, valores: dict) -> dict:
    campos = {}
    for linea in plantilla.splitlines():
        if "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        campos[clave.strip()] = _PATRON.sub(lambda m: valores[m.group(1)], valor.strip())
    return campos


def _enviar_con_proveedor(destino: str, texto: str) -> str:
    """Llama a la API del proveedor según la configuración guardada. Lanza SmsFallo si no se pudo enviar.

    Devuelve SIN_CONFIRMACION si el proveedor no alcanzó a responder a tiempo: el mensaje ya salió de aquí
    y puede haber llegado, así que no se trata como un fallo."""
    cfg = _config()
    if not cfg or not cfg["url"]:
        raise SmsFallo("La API del proveedor no está configurada")
    headers: dict[str, str] = {}
    auth = None
    tipo = cfg["auth_tipo"]
    secreto = (cfg["auth_secreto"] or "").strip().strip("\"'").strip()
    if tipo != "ninguna" and not secreto:
        raise SmsFallo("Falta la clave o el token de la API: pégalo en la tuerca de Mensajería y guarda")
    if tipo == "basic":
        auth = (cfg["auth_usuario"].strip(), secreto)
    elif tipo == "bearer":
        headers["Authorization"] = f"Bearer {secreto}"
    elif tipo == "header":
        headers[(cfg["auth_header_nombre"] or "X-API-Key").strip()] = secreto

    valores = {"telefono": destino, "mensaje": texto, "remitente": cfg["remitente"], "usuario": cfg["auth_usuario"]}
    kwargs: dict = {}
    try:
        if cfg["content_type"] == "json":
            headers["Content-Type"] = "application/json"
            cuerpo = _cuerpo_json(cfg["cuerpo_plantilla"], valores)
            if cfg["metodo"] == "GET":
                kwargs["params"] = json.loads(cuerpo)
            else:
                kwargs["content"] = cuerpo.encode("utf-8")
        else:
            kwargs["params" if cfg["metodo"] == "GET" else "data"] = _campos_form(cfg["cuerpo_plantilla"], valores)
        resp = httpx.request(cfg["metodo"], cfg["url"], headers=headers, auth=auth, timeout=_TIMEOUT_S, **kwargs)
    except httpx.ReadTimeout:
        return SIN_CONFIRMACION
    except (httpx.HTTPError, ValueError) as exc:
        raise SmsFallo(f"No se pudo conectar con el proveedor: {type(exc).__name__} {str(exc)[:120]}".strip()) from exc

    detalle = resp.text[:300].replace("\n", " ")
    if not 200 <= resp.status_code < 300:
        raise SmsFallo(f"El proveedor respondió HTTP {resp.status_code}: {detalle}")
    if cfg["exito_contiene"] and cfg["exito_contiene"] not in resp.text:
        raise SmsFallo(f"La respuesta no contiene «{cfg['exito_contiene']}»: {detalle}")
    return "ok"


def enviar_sms(conn, usuario_id: int | None, telefono: str, texto: str, proposito: str, pais: str | None) -> None:
    """Envía y deja constancia en sms_envios, haya salido bien o no."""
    if not sms_configurado():
        raise SmsNoConfigurado()
    destino = a_internacional(telefono, pais)
    estado, error = "enviado", ""
    try:
        if _enviar_con_proveedor(destino, texto) == SIN_CONFIRMACION:
            error = "Sin confirmación del proveedor (tiempo agotado): el mensaje pudo haber llegado"
    except SmsFallo as exc:
        estado, error = "fallido", str(exc)[:500]
        logger.warning("SMS fallido a %s: %s", destino[-4:], error)
    finally:
        conn.run(
            "INSERT INTO sms_envios (usuario_id, telefono, proposito, estado, proveedor, error, pais) "
            "VALUES (:u, :t, :p, :e, :pr, :er, :pa)",
            u=usuario_id, t=destino, p=proposito, e=estado, pr=proveedor(), er=error, pa=(pais or None),
        )
    if estado == "fallido":
        raise SmsFallo(error)


def emitir_codigo(conn, usuario_id: int, telefono: str, pais: str | None) -> dict:
    """Genera un código, lo envía por SMS y lo guarda (solo su hash). Devuelve cuándo se puede reenviar."""
    ahora = datetime.now(timezone.utc)
    ultimo = conn.run(
        "SELECT created_at FROM verificaciones_telefono WHERE usuario_id = :u ORDER BY created_at DESC LIMIT 1",
        u=usuario_id,
    )
    if ultimo:
        espera = REENVIO_ESPERA_S - (ahora - ultimo[0][0]).total_seconds()
        if espera > 0:
            return {"ok": False, "esperar_s": int(espera) + 1, "motivo": "espera"}
    ultima_hora = conn.run(
        "SELECT count(*) FROM verificaciones_telefono WHERE usuario_id = :u AND created_at > :d",
        u=usuario_id, d=ahora - timedelta(hours=1),
    )[0][0]
    if ultima_hora >= MAX_ENVIOS_POR_HORA:
        return {"ok": False, "esperar_s": 3600, "motivo": "limite"}

    codigo = generar_codigo()
    texto = f"Violet: tu código de verificación es {codigo}. Vence en {CODIGO_VIGENCIA_MIN} minutos. No lo compartas."
    vid = conn.run(
        "INSERT INTO verificaciones_telefono (usuario_id, telefono, codigo_hash, expira_en) VALUES (:u, :t, :h, :x) RETURNING id",
        u=usuario_id, t=solo_digitos(telefono), h=_hash_codigo(usuario_id, codigo),
        x=ahora + timedelta(minutes=CODIGO_VIGENCIA_MIN),
    )[0][0]
    try:
        enviar_sms(conn, usuario_id, telefono, texto, "verificacion", pais)
    except Exception:
        # No salió: se descarta el código para no gastar el tiempo de espera de quien lo pidió.
        conn.run("DELETE FROM verificaciones_telefono WHERE id = :i", i=vid)
        raise
    return {"ok": True, "esperar_s": REENVIO_ESPERA_S, "motivo": ""}


def comprobar_codigo(conn, usuario_id: int, codigo: str) -> str:
    """'ok', 'incorrecto', 'vencido' o 'bloqueado'. Con 'ok' deja el teléfono marcado como verificado.

    Se acepta cualquiera de los últimos códigos vigentes: si pidieron otro porque el SMS tardó, el primero
    que llegue también sirve.
    """
    ahora = datetime.now(timezone.utc)
    filas = conn.run(
        "SELECT id, telefono, codigo_hash, intentos, expira_en FROM verificaciones_telefono "
        "WHERE usuario_id = :u AND verificado_en IS NULL ORDER BY created_at DESC LIMIT 3",
        u=usuario_id,
    )
    vigentes = [f for f in filas if f[4] >= ahora]
    if not vigentes:
        return "vencido"
    if all(f[3] >= MAX_INTENTOS for f in vigentes):
        return "bloqueado"
    digitos = solo_digitos(codigo)
    for vid, telefono, esperado, intentos, _ in vigentes:
        if intentos < MAX_INTENTOS and hmac.compare_digest(esperado, _hash_codigo(usuario_id, digitos)):
            conn.run("UPDATE verificaciones_telefono SET verificado_en = now() WHERE id = :i", i=vid)
            conn.run("UPDATE usuarios SET telefono_verificado = :t WHERE id = :u", t=telefono, u=usuario_id)
            return "ok"
    for vid, _, _, intentos, _ in vigentes:
        conn.run("UPDATE verificaciones_telefono SET intentos = intentos + 1 WHERE id = :i", i=vid)
    return "bloqueado" if all(f[3] + 1 >= MAX_INTENTOS for f in vigentes) else "incorrecto"


def telefono_con_codigo_pendiente(conn, usuario_id: int) -> str:
    """Teléfono al que se mandó un código que aún no vence ni se ha usado ('' si no hay)."""
    if not sms_configurado():
        return ""
    fila = conn.run(
        "SELECT telefono FROM verificaciones_telefono WHERE usuario_id = :u AND verificado_en IS NULL "
        "AND expira_en > now() AND intentos < :m ORDER BY created_at DESC LIMIT 1",
        u=usuario_id, m=MAX_INTENTOS,
    )
    return fila[0][0] if fila else ""
