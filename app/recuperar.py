"""Recuperar la contraseña: código de 6 dígitos por SMS al teléfono de la cuenta.

Flujo: 1) solicitar (correo o documento) → SMS con el código; 2) verificar el código → token de un solo uso;
3) cambiar la contraseña con ese token.

Para no revelar qué correos tienen cuenta, «solicitar» responde igual exista o no la cuenta (y tenga o no
teléfono). Cada cuenta tiene una espera entre envíos y un tope por hora, y cada IP un tope por hora.
"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import sms
from app.database import get_connection
from app.security import hash_password

router = APIRouter(prefix="/auth/recuperar", tags=["auth"])

CODIGO_DIGITOS = 6
CODIGO_VIGENCIA_MIN = 10
TOKEN_VIGENCIA_MIN = 15
ESPERA_S = 180
MAX_ENVIOS_HORA = 5
MAX_INTENTOS = 5
MAX_PEDIDOS_IP_HORA = 20

_pedidos_ip: dict[str, list[float]] = {}


class SolicitarIn(BaseModel):
    identificador: str = Field(min_length=3, max_length=150)


class SolicitarOut(BaseModel):
    ok: bool = True
    esperar_s: int = ESPERA_S


class VerificarIn(BaseModel):
    identificador: str = Field(min_length=3, max_length=150)
    codigo: str = Field(min_length=CODIGO_DIGITOS, max_length=CODIGO_DIGITOS, pattern=r"^[0-9]{6}$")


class VerificarOut(BaseModel):
    token: str


class CambiarIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=6, max_length=72)


class CambiarOut(BaseModel):
    ok: bool = True


def _hash(valor: str, contexto: str) -> str:
    # Con el secreto de la app, para que un volcado de la tabla no permita adivinar los códigos de 6 dígitos.
    return hmac.new(sms._secreto(), f"{contexto}:{valor}".encode(), hashlib.sha256).hexdigest()


def _limite_ip(request: Request) -> None:
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    ahora = time.time()
    recientes = [t for t in _pedidos_ip.get(ip, []) if ahora - t < 3600]
    if len(recientes) >= MAX_PEDIDOS_IP_HORA:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Demasiados intentos. Inténtalo en una hora.")
    recientes.append(ahora)
    _pedidos_ip[ip] = recientes
    if len(_pedidos_ip) > 5000:  # evita que el diccionario crezca sin fin
        for clave in [k for k, v in _pedidos_ip.items() if not v or ahora - v[-1] > 3600]:
            _pedidos_ip.pop(clave, None)


def _buscar_cuenta(conn, identificador: str):
    rows = conn.run(
        "SELECT id, telefono, pais, activo FROM usuarios WHERE lower(email) = lower(:i) OR numero_documento = :i LIMIT 1",
        i=identificador.strip(),
    )
    return rows[0] if rows else None


@router.post("/solicitar", response_model=SolicitarOut)
def solicitar(payload: SolicitarIn, request: Request):
    if not sms.sms_configurado():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperación por SMS no está disponible en este momento. Escríbenos a soporte.",
        )
    _limite_ip(request)
    conn = get_connection()
    try:
        cuenta = _buscar_cuenta(conn, payload.identificador)
        # Misma respuesta exista o no la cuenta: no se revela qué correos están registrados.
        if not cuenta or not cuenta[3] or len(sms.solo_digitos(cuenta[1])) < 7:
            return SolicitarOut()
        uid, telefono, pais = cuenta[0], cuenta[1], cuenta[2]

        ahora = datetime.now(timezone.utc)
        ultimo = conn.run(
            "SELECT created_at FROM recuperaciones_clave WHERE usuario_id = :u ORDER BY created_at DESC LIMIT 1", u=uid,
        )
        if ultimo and (ahora - ultimo[0][0]).total_seconds() < ESPERA_S:
            return SolicitarOut()
        ultima_hora = conn.run(
            "SELECT count(*) FROM recuperaciones_clave WHERE usuario_id = :u AND created_at > :d",
            u=uid, d=ahora - timedelta(hours=1),
        )[0][0]
        if ultima_hora >= MAX_ENVIOS_HORA:
            return SolicitarOut()

        codigo = sms.generar_codigo(CODIGO_DIGITOS)
        rid = conn.run(
            "INSERT INTO recuperaciones_clave (usuario_id, codigo_hash, expira_en) VALUES (:u, :h, :x) RETURNING id",
            u=uid, h=_hash(codigo, f"cod:{uid}"), x=ahora + timedelta(minutes=CODIGO_VIGENCIA_MIN),
        )[0][0]
        texto = (
            f"Violet: tu código para recuperar la contraseña es {codigo}. Vence en {CODIGO_VIGENCIA_MIN} minutos. "
            "Si no lo pediste, ignora este mensaje."
        )
        try:
            sms.enviar_sms(conn, uid, telefono, texto, "recuperacion", pais)
        except sms.SmsFallo:
            conn.run("DELETE FROM recuperaciones_clave WHERE id = :i", i=rid)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No pudimos enviar el mensaje. Inténtalo de nuevo en unos minutos.",
            )
        return SolicitarOut()
    finally:
        conn.close()


@router.post("/verificar", response_model=VerificarOut)
def verificar(payload: VerificarIn, request: Request):
    _limite_ip(request)
    conn = get_connection()
    try:
        cuenta = _buscar_cuenta(conn, payload.identificador)
        incorrecto = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código incorrecto. Revisa el mensaje e inténtalo de nuevo.")
        if not cuenta:
            raise incorrecto
        uid = cuenta[0]
        ahora = datetime.now(timezone.utc)
        filas = conn.run(
            "SELECT id, codigo_hash, intentos, expira_en FROM recuperaciones_clave "
            "WHERE usuario_id = :u AND usado_en IS NULL ORDER BY created_at DESC LIMIT 3",
            u=uid,
        )
        vigentes = [f for f in filas if f[3] >= ahora]
        if not vigentes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El código venció. Pide uno nuevo.")
        if all(f[2] >= MAX_INTENTOS for f in vigentes):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Demasiados intentos. Pide un código nuevo.")

        esperado = _hash(payload.codigo, f"cod:{uid}")
        for rid, hash_codigo, intentos, _ in vigentes:
            if intentos < MAX_INTENTOS and hmac.compare_digest(hash_codigo, esperado):
                token = secrets.token_urlsafe(32)
                conn.run(
                    "UPDATE recuperaciones_clave SET usado_en = now(), token_hash = :t, token_expira_en = :x WHERE id = :i",
                    t=_hash(token, "tok"), x=ahora + timedelta(minutes=TOKEN_VIGENCIA_MIN), i=rid,
                )
                # Los demás códigos pendientes de esta cuenta dejan de servir.
                conn.run(
                    "UPDATE recuperaciones_clave SET usado_en = now() WHERE usuario_id = :u AND usado_en IS NULL", u=uid,
                )
                return VerificarOut(token=token)
        for rid, _, _, _ in vigentes:
            conn.run("UPDATE recuperaciones_clave SET intentos = intentos + 1 WHERE id = :i", i=rid)
        raise incorrecto
    finally:
        conn.close()


@router.post("/cambiar", response_model=CambiarOut)
def cambiar(payload: CambiarIn, request: Request):
    _limite_ip(request)
    conn = get_connection()
    try:
        fila = conn.run(
            "SELECT id, usuario_id FROM recuperaciones_clave "
            "WHERE token_hash = :h AND token_expira_en > now() AND token_usado_en IS NULL",
            h=_hash(payload.token, "tok"),
        )
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El enlace para cambiar la contraseña venció. Empieza de nuevo.",
            )
        rid, uid = fila[0]
        conn.run("UPDATE usuarios SET password_hash = :p WHERE id = :u", p=hash_password(payload.password), u=uid)
        conn.run("UPDATE recuperaciones_clave SET token_usado_en = now() WHERE id = :i", i=rid)
        return CambiarOut()
    finally:
        conn.close()
