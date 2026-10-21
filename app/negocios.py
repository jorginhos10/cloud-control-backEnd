from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app import sms
from app.auth import UserOut, get_current_user, require_roles
from app.database import get_connection, get_superadmin_connection
from app.moneda import moneda_de_cuenta
from app.schemas import (
    NegocioAparienciaIn,
    NegocioAparienciaOut,
    NegocioIn,
    NegocioOut,
    TelefonoCodigoIn,
    TelefonoCodigoOut,
    TelefonoEstadoOut,
    TelefonoVerificarIn,
    TelefonoVerificarOut,
)

router = APIRouter(prefix="/negocio", dependencies=[Depends(get_current_user)])

NEGOCIO_EDIT_COLUMNS = [
    "nombre", "tipo", "moneda", "eslogan", "horario_apertura", "horario_cierre",
    "rut", "direccion", "ciudad", "telefono", "email", "sitio_web", "logo_url",
]
NEGOCIO_COLUMNS = NEGOCIO_EDIT_COLUMNS + ["updated_at"]

# Debe reflejar exactamente los AparienciaId que existen en este front.
APARIENCIAS_CONOCIDAS = ["automatico", "violet-original", "violet-tableta", "halloween", "navidad", "modo-nocturno"]


def _apariencias_permitidas(tenant_id: int) -> list[str]:
    """Qué apariencias puede elegir este comercio, según la regla que el
    SuperAdmin haya configurado para cada una (todos / nadie / todos_menos /
    solo). Si el SuperAdmin no está disponible, no bloqueamos a nadie."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return list(APARIENCIAS_CONOCIDAS)

    try:
        reglas = dict(sconn.run("SELECT apariencia_key, visibilidad FROM apariencia_reglas"))
        comercios_por_key: dict[str, set[int]] = {}
        for key, comercio_id in sconn.run("SELECT apariencia_key, comercio_id FROM apariencia_comercios"):
            comercios_por_key.setdefault(key, set()).add(comercio_id)
    finally:
        sconn.close()

    permitidas = []
    for key in APARIENCIAS_CONOCIDAS:
        visibilidad = reglas.get(key, "todos")
        comercios = comercios_por_key.get(key, set())
        if visibilidad == "nadie":
            continue
        if visibilidad == "todos_menos" and tenant_id in comercios:
            continue
        if visibilidad == "solo" and tenant_id not in comercios:
            continue
        permitidas.append(key)
    return permitidas


def _negocio_por_defecto(moneda: str) -> NegocioOut:
    return NegocioOut(moneda=moneda, updated_at=datetime.now(timezone.utc))


@router.get("", response_model=NegocioOut)
def get_negocio(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(NEGOCIO_COLUMNS)} FROM negocios WHERE usuario_id = :id",
            id=current_user.tenant_id,
        )
        # The currency is derived from the country the account signed up in, not chosen or stored-as-typed.
        moneda = moneda_de_cuenta(current_user.tenant_id)
        if not rows:
            return _negocio_por_defecto(moneda)
        return NegocioOut(**{**dict(zip(NEGOCIO_COLUMNS, rows[0])), "moneda": moneda})
    finally:
        conn.close()


@router.put("", response_model=NegocioOut)
def guardar_negocio(payload: NegocioIn, current_user: UserOut = Depends(require_roles("admin"))):
    conn = get_connection()
    try:
        telefono_cambio = _exigir_telefono_verificado(conn, current_user, payload.telefono)
        rows = conn.run(
            f"""
            INSERT INTO negocios (usuario_id, {', '.join(NEGOCIO_EDIT_COLUMNS)})
            VALUES (:uid, :nombre, :tipo, :moneda, :eslogan, :horario_apertura, :horario_cierre,
                    :rut, :direccion, :ciudad, :telefono, :email, :sitio_web, :logo_url)
            ON CONFLICT (usuario_id) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                tipo = EXCLUDED.tipo,
                moneda = EXCLUDED.moneda,
                eslogan = EXCLUDED.eslogan,
                horario_apertura = EXCLUDED.horario_apertura,
                horario_cierre = EXCLUDED.horario_cierre,
                rut = EXCLUDED.rut,
                direccion = EXCLUDED.direccion,
                ciudad = EXCLUDED.ciudad,
                telefono = EXCLUDED.telefono,
                email = EXCLUDED.email,
                sitio_web = EXCLUDED.sitio_web,
                logo_url = EXCLUDED.logo_url,
                updated_at = now()
            RETURNING {', '.join(NEGOCIO_COLUMNS)}
            """,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            tipo=payload.tipo,
            moneda=moneda_de_cuenta(current_user.tenant_id),
            eslogan=payload.eslogan.strip(),
            horario_apertura=payload.horario_apertura,
            horario_cierre=payload.horario_cierre,
            rut=payload.rut.strip(),
            direccion=payload.direccion.strip(),
            ciudad=payload.ciudad.strip(),
            telefono=payload.telefono.strip(),
            email=payload.email.strip(),
            sitio_web=payload.sitio_web.strip(),
            logo_url=payload.logo_url,
        )
        # El teléfono del propietario es al que llega el SMS de recuperación de contraseña: si acaba de
        # verificar uno nuevo, ese pasa a ser el de su cuenta.
        if telefono_cambio and current_user.propietario:
            conn.run("UPDATE usuarios SET telefono = :t WHERE id = :id", t=payload.telefono.strip(), id=current_user.id)
        return NegocioOut(**dict(zip(NEGOCIO_COLUMNS, rows[0])))
    finally:
        conn.close()


def _pais_del_comercio(conn, tenant_id: int) -> str | None:
    rows = conn.run("SELECT pais FROM usuarios WHERE id = :id", id=tenant_id)
    return rows[0][0] if rows else None


def _exigir_telefono_verificado(conn, current_user: UserOut, telefono: str) -> bool:
    """Si la verificación por SMS aplica al país del comercio, un teléfono nuevo debe estar verificado.

    Devuelve True cuando el teléfono cambió (y, de ser necesario, ya estaba verificado). Un teléfono que no se
    toca no pide verificación: las cuentas anteriores a esta regla siguen guardando sin problema.
    """
    nuevo = sms.solo_digitos(telefono)
    actual = conn.run("SELECT telefono FROM negocios WHERE usuario_id = :id", id=current_user.tenant_id)
    anterior = sms.solo_digitos(actual[0][0]) if actual else ""
    if not nuevo or nuevo == anterior:
        return False
    if sms.verificacion_requerida(_pais_del_comercio(conn, current_user.tenant_id)):
        verificado = conn.run("SELECT telefono_verificado FROM usuarios WHERE id = :id", id=current_user.id)[0][0]
        if verificado != nuevo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verifica el nuevo teléfono con el código que te enviamos por SMS",
            )
    return True


@router.get("/telefono/estado", response_model=TelefonoEstadoOut)
def estado_telefono(current_user: UserOut = Depends(require_roles("admin"))):
    conn = get_connection()
    try:
        requerida = sms.verificacion_requerida(_pais_del_comercio(conn, current_user.tenant_id))
        verificado = conn.run("SELECT telefono_verificado FROM usuarios WHERE id = :id", id=current_user.id)[0][0]
        return TelefonoEstadoOut(
            requerida=requerida,
            telefono_verificado=verificado or "",
            codigo_pendiente_telefono=sms.telefono_con_codigo_pendiente(conn, current_user.id) if requerida else "",
        )
    finally:
        conn.close()


@router.post("/telefono/codigo", response_model=TelefonoCodigoOut)
def enviar_codigo_telefono(payload: TelefonoCodigoIn, current_user: UserOut = Depends(require_roles("admin"))):
    """Manda por SMS un código de 4 dígitos al teléfono nuevo del comercio."""
    digitos = sms.solo_digitos(payload.telefono)
    if len(digitos) < 7:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escribe un número de teléfono válido")
    conn = get_connection()
    try:
        pais = _pais_del_comercio(conn, current_user.tenant_id)
        if not sms.verificacion_requerida(pais):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="La verificación por SMS no está disponible")
        if conn.run("SELECT 1 FROM usuarios WHERE telefono_verificado = :t AND id <> :id", t=digitos, id=current_user.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese número ya está registrado en otra cuenta")
        try:
            resultado = sms.emitir_codigo(conn, current_user.id, payload.telefono, pais)
        except sms.SmsFallo:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No pudimos enviar el mensaje. Revisa el número e inténtalo de nuevo.",
            )
        if not resultado["ok"] and resultado["motivo"] == "limite":
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Pediste demasiados códigos. Inténtalo en una hora.")
        return TelefonoCodigoOut(**resultado)
    finally:
        conn.close()


@router.post("/telefono/verificar", response_model=TelefonoVerificarOut)
def verificar_codigo_telefono(payload: TelefonoVerificarIn, current_user: UserOut = Depends(require_roles("admin"))):
    conn = get_connection()
    try:
        resultado = sms.comprobar_codigo(conn, current_user.id, payload.codigo)
        if resultado == "ok":
            verificado = conn.run("SELECT telefono_verificado FROM usuarios WHERE id = :id", id=current_user.id)[0][0]
            return TelefonoVerificarOut(verificado=True, resultado="ok", telefono_verificado=verificado)
        return TelefonoVerificarOut(verificado=False, resultado=resultado)
    finally:
        conn.close()


def _tema_automatico_default() -> str:
    """Estilo que el SuperAdmin marco con la estrella en Apariencias > Sistema: es a lo que
    cae "Automático" fuera de temporada (Halloween/Navidad). Si el SuperAdmin no responde,
    usamos el estilo por defecto de siempre."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return "violet-original"
    try:
        rows = sconn.run("SELECT apariencia_key FROM apariencia_automatico WHERE id = 1")
        return rows[0][0] if rows else "violet-original"
    except Exception:
        return "violet-original"
    finally:
        sconn.close()


def resolver_apariencia_publica(apariencia: str) -> str:
    """Resuelve "Automático" a un estilo concreto para páginas públicas (menú, domicilios):
    ahí no hay sesión desde la que el front pueda pedir el estilo por defecto del SuperAdmin,
    así que hay que mandarlo ya resuelto. Debe reflejar las mismas fechas que
    ThemeService.temaPorFecha en el frontend (Halloween en octubre, Navidad en diciembre)."""
    if apariencia != "automatico":
        return apariencia
    mes = datetime.now().month
    if mes == 10:
        return "halloween"
    if mes == 12:
        return "navidad"
    return _tema_automatico_default()


@router.get("/apariencia", response_model=NegocioAparienciaOut)
def get_apariencia(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run("SELECT apariencia FROM negocios WHERE usuario_id = :id", id=current_user.tenant_id)
        return NegocioAparienciaOut(
            apariencia=rows[0][0] if rows else "violet-original",
            automatico_default=_tema_automatico_default(),
        )
    finally:
        conn.close()


def _imagenes_apariencias() -> dict[str, str]:
    """Vista previa que el SuperAdmin cargó para cada apariencia. Vacío si no hay ninguna o el panel no responde."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return {}
    try:
        return dict(sconn.run("SELECT apariencia_key, imagen FROM apariencia_imagenes"))
    except Exception:
        return {}
    finally:
        sconn.close()


@router.get("/apariencias-permitidas")
def get_apariencias_permitidas(current_user: UserOut = Depends(get_current_user)):
    return {"apariencias": _apariencias_permitidas(current_user.tenant_id), "imagenes": _imagenes_apariencias()}


@router.put("/apariencia", response_model=NegocioAparienciaOut)
def set_apariencia(payload: NegocioAparienciaIn, current_user: UserOut = Depends(require_roles("admin"))):
    if payload.apariencia not in _apariencias_permitidas(current_user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta apariencia no está disponible para tu comercio",
        )

    conn = get_connection()
    try:
        conn.run(
            "INSERT INTO negocios (usuario_id, apariencia) VALUES (:uid, :apariencia) "
            "ON CONFLICT (usuario_id) DO UPDATE SET apariencia = EXCLUDED.apariencia, updated_at = now()",
            uid=current_user.tenant_id, apariencia=payload.apariencia,
        )
        return NegocioAparienciaOut(apariencia=payload.apariencia)
    finally:
        conn.close()
