"""Envío de SMS y verificación del teléfono con un código de 4 dígitos.

El envío real depende del proveedor de SMS (variable de entorno SMS_PROVIDER). Mientras no haya uno
configurado, la verificación queda apagada y el registro funciona como siempre: así nadie se queda sin
poder registrarse por un servicio que todavía no está conectado.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("sms")

CODIGO_VIGENCIA_MIN = 10
MAX_INTENTOS = 5
REENVIO_ESPERA_S = 60
MAX_ENVIOS_POR_HORA = 5


class SmsNoConfigurado(Exception):
    """No hay proveedor de SMS configurado."""


class SmsFallo(Exception):
    """El proveedor rechazó o no pudo entregar el mensaje."""


def proveedor() -> str:
    return os.environ.get("SMS_PROVIDER", "").strip().lower()


def sms_configurado() -> bool:
    return bool(proveedor())


def solo_digitos(telefono: str) -> str:
    return re.sub(r"\D", "", telefono or "")


def a_internacional(telefono: str, pais: str | None) -> str:
    """Dígitos con indicativo de país, que es lo que piden los proveedores (57300… para Colombia)."""
    d = solo_digitos(telefono)
    if d.startswith("00"):
        d = d[2:]
    if (pais or "CO").upper() == "CO" and len(d) == 10 and d.startswith("3"):
        return "57" + d
    return d


def _hash_codigo(usuario_id: int, codigo: str) -> str:
    secreto = os.environ.get("JWT_SECRET", "violet").encode()
    return hmac.new(secreto, f"{usuario_id}:{codigo}".encode(), hashlib.sha256).hexdigest()


def generar_codigo() -> str:
    """4 dígitos, fáciles de teclear; se descartan los que son todos iguales (0000, 7777…)."""
    while True:
        codigo = f"{secrets.randbelow(10000):04d}"
        if len(set(codigo)) > 1:
            return codigo


def _enviar_con_proveedor(destino: str, texto: str) -> None:
    """Entrega el SMS por el proveedor configurado. Debe lanzar SmsFallo si no se pudo enviar."""
    prov = proveedor()
    if prov == "inalambria":
        # Pendiente de conectar: necesito la documentación de la API de Inalámbria (URL, formato de
        # autenticación y cuerpo del envío) y las credenciales de la cuenta para escribir esta llamada.
        raise SmsFallo("El proveedor 'inalambria' todavía no está implementado")
    raise SmsFallo(f"Proveedor de SMS desconocido: {prov}")


def enviar_sms(conn, usuario_id: int | None, telefono: str, texto: str, proposito: str, pais: str | None) -> None:
    """Envía y deja constancia en sms_envios, haya salido bien o no."""
    if not sms_configurado():
        raise SmsNoConfigurado()
    destino = a_internacional(telefono, pais)
    estado, error = "enviado", ""
    try:
        _enviar_con_proveedor(destino, texto)
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
    enviar_sms(conn, usuario_id, telefono, texto, "verificacion", pais)
    conn.run(
        "INSERT INTO verificaciones_telefono (usuario_id, telefono, codigo_hash, expira_en) VALUES (:u, :t, :h, :x)",
        u=usuario_id, t=solo_digitos(telefono), h=_hash_codigo(usuario_id, codigo),
        x=ahora + timedelta(minutes=CODIGO_VIGENCIA_MIN),
    )
    return {"ok": True, "esperar_s": REENVIO_ESPERA_S, "motivo": ""}


def comprobar_codigo(conn, usuario_id: int, codigo: str) -> str:
    """'ok', 'incorrecto', 'vencido' o 'bloqueado'. Con 'ok' deja el teléfono marcado como verificado."""
    ahora = datetime.now(timezone.utc)
    fila = conn.run(
        "SELECT id, telefono, codigo_hash, intentos, expira_en FROM verificaciones_telefono "
        "WHERE usuario_id = :u AND verificado_en IS NULL ORDER BY created_at DESC LIMIT 1",
        u=usuario_id,
    )
    if not fila:
        return "vencido"
    vid, telefono, esperado, intentos, expira = fila[0]
    if expira < ahora:
        return "vencido"
    if intentos >= MAX_INTENTOS:
        return "bloqueado"
    conn.run("UPDATE verificaciones_telefono SET intentos = intentos + 1 WHERE id = :i", i=vid)
    if not hmac.compare_digest(esperado, _hash_codigo(usuario_id, solo_digitos(codigo))):
        return "bloqueado" if intentos + 1 >= MAX_INTENTOS else "incorrecto"
    conn.run("UPDATE verificaciones_telefono SET verificado_en = now() WHERE id = :i", i=vid)
    conn.run("UPDATE usuarios SET telefono_verificado = :t WHERE id = :u", t=telefono, u=usuario_id)
    return "ok"
