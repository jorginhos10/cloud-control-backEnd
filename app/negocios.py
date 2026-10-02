from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user, require_roles
from app.database import get_connection, get_superadmin_connection
from app.moneda import moneda_de_cuenta
from app.schemas import NegocioAparienciaIn, NegocioAparienciaOut, NegocioIn, NegocioOut

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
        return NegocioOut(**dict(zip(NEGOCIO_COLUMNS, rows[0])))
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
