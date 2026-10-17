"""Cierre Z automático: cada minuto revisa si algún comercio tiene activado el cierre
automático y es su hora, y si toca, genera el cierre solo (mismo efecto que si alguien
apretara "Generar cierre Z" a mano).

El backend corre con varios workers de uvicorn, cada uno con su propio scheduler en proceso;
sin coordinación, los dos dispararían el mismo cierre al mismo tiempo. `pg_try_advisory_lock`
hace que solo el worker que gana la carrera por el candado haga el trabajo en cada tick.

La hora que guarda el comercio es la hora local de Colombia (America/Bogota, UTC-5, sin
horario de verano); el servidor corre en UTC, así que se convierte sumando 5 antes de comparar.
"""
import logging
from datetime import datetime

from app.database import get_connection
from app.reportes import generar_cierre

logger = logging.getLogger("scheduler")

_LOCK_KEY = 727001
_BOGOTA_UTC_OFFSET = 5
_VENTANA_IDEMPOTENCIA_MIN = 50


def ejecutar_cierres_automaticos() -> None:
    conn = get_connection()
    try:
        obtuvo_lock = conn.run("SELECT pg_try_advisory_lock(:k)", k=_LOCK_KEY)[0][0]
        if not obtuvo_lock:
            return
        try:
            _procesar_tick(conn)
        finally:
            conn.run("SELECT pg_advisory_unlock(:k)", k=_LOCK_KEY)
    except Exception:
        logger.exception("Fallo en el tick del scheduler de cierres automáticos")
    finally:
        conn.close()


def _procesar_tick(conn) -> None:
    ahora = datetime.now()  # naive, equivalente a UTC (el servidor corre en UTC)
    if ahora.minute != 0:
        return

    hora_bogota = (ahora.hour - _BOGOTA_UTC_OFFSET) % 24
    tenants = conn.run(
        "SELECT usuario_id FROM negocios WHERE cierre_automatico_activo = true AND cierre_automatico_hora = :hora",
        hora=hora_bogota,
    )
    for (usuario_id,) in tenants:
        ultimo = conn.run(
            "SELECT created_at FROM cierres_z WHERE usuario_id = :uid ORDER BY created_at DESC LIMIT 1",
            uid=usuario_id,
        )
        if ultimo and (ahora - ultimo[0][0]).total_seconds() < _VENTANA_IDEMPOTENCIA_MIN * 60:
            continue  # ya se generó uno (automático o manual) hace muy poco para este comercio
        try:
            cierre = generar_cierre(conn, usuario_id, automatico=True)
            logger.info("Cierre Z automático #%s generado para usuario_id=%s", cierre.numero_z, usuario_id)
        except Exception:
            logger.exception("Fallo generando el cierre Z automático de usuario_id=%s", usuario_id)
