import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user_any_status
from app.database import get_connection, get_superadmin_connection
from app.moneda import moneda_de_cuenta
from app.schemas import (
    OnboardingDatosIn,
    OnboardingDocumentoIn,
    OnboardingLogoIn,
    OnboardingOut,
    OnboardingPlanIn,
    PlanPublicoOut,
    UserOut,
)
from app.suscripcion import _fetch_plan_disponible, listar_planes_disponibles

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

EDITABLE_STATES = ("pendiente_datos", "rechazado")
MAX_DOC_BYTES = 5 * 1024 * 1024
MAX_DOCS = 8
LOGO_DATA_URL = re.compile(r"^data:image/(png|jpe?g|webp|gif|svg\+xml);base64,")
REQUIRED_DOCS = [
    ("identificacion_fiscal", "Identificación fiscal (RUT / NIT)"),
    ("documento_representante", "Documento de identidad del representante"),
]
DOC_COLUMNS = ["id", "tipo", "nombre_archivo", "content_type", "tamano", "created_at", "estado", "motivo_rechazo"]
DOC_LABELS = {
    "identificacion_fiscal": "Identificación fiscal (RUT / NIT)",
    "documento_representante": "Documento de identidad del representante",
    "camara_comercio": "Cámara de Comercio",
    "otro": "Otro documento",
}
FILE_SIGNATURES = [
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


def _require_editable(user: UserOut) -> None:
    if not user.propietario:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede completar el registro")
    if user.estado_aprobacion == "pendiente_aprobacion":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tu solicitud ya está en revisión")
    if user.estado_aprobacion not in EDITABLE_STATES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tu cuenta ya fue aprobada")


def _tipos_comercio_habilitados() -> list[str]:
    """El SuperAdmin puede apagar Store y/o Restobar como opciones de registro desde su panel de Configuraciones."""
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return ["Store", "Restobar"]
    try:
        rows = sconn.run("SELECT tipo_store_habilitado, tipo_restobar_habilitado FROM ajustes_generales WHERE id = 1")
        if not rows:
            return ["Store", "Restobar"]
        tipos = []
        if rows[0][0]:
            tipos.append("Store")
        if rows[0][1]:
            tipos.append("Restobar")
        return tipos or ["Store", "Restobar"]
    except Exception:
        return ["Store", "Restobar"]
    finally:
        sconn.close()


def _estado_completo(conn, user_id: int) -> OnboardingOut:
    row = conn.run(
        """
        SELECT u.numero_documento, u.telefono, u.estado_aprobacion, u.motivo_rechazo, u.plan_solicitado_id,
               n.nombre, n.tipo, n.rut, n.direccion, n.ciudad, n.sitio_web, n.logo_url
        FROM usuarios u LEFT JOIN negocios n ON n.usuario_id = u.id
        WHERE u.id = :id
        """,
        id=user_id,
    )[0]
    documentos = conn.run(
        "SELECT id, tipo, nombre_archivo, content_type, tamano, created_at, estado, motivo_rechazo "
        "FROM comercio_documentos WHERE usuario_id = :id ORDER BY created_at",
        id=user_id,
    )
    return OnboardingOut(
        numero_documento=row[0],
        telefono=row[1],
        estado_aprobacion=row[2],
        motivo_rechazo=row[3],
        plan_solicitado_id=row[4],
        nombre_negocio=row[5] or "",
        tipo_negocio=row[6] or "Restaurante",
        rut=row[7] or "",
        direccion=row[8] or "",
        ciudad=row[9] or "",
        sitio_web=row[10] or "",
        logo_url=row[11],
        documentos=[dict(zip(DOC_COLUMNS, d)) for d in documentos],
        tipos_comercio_habilitados=_tipos_comercio_habilitados(),
    )


def _tipo_de_archivo(data: bytes) -> str | None:
    return next((mime for firma, mime in FILE_SIGNATURES if data.startswith(firma)), None)


@router.get("", response_model=OnboardingOut)
def obtener(current_user: UserOut = Depends(get_current_user_any_status)):
    if not current_user.propietario:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede completar el registro")
    conn = get_connection()
    try:
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


def _descartar_plan_no_disponible(conn, usuario_id: int) -> None:
    """Changing the type of commerce can leave the requested plan outside the merchant's list of plans;
    drop it so they pick one of the plans that do apply."""
    pid = conn.run("SELECT plan_solicitado_id FROM usuarios WHERE id = :id", id=usuario_id)[0][0]
    if pid is None:
        return
    try:
        sconn = get_superadmin_connection()
    except Exception:
        return
    try:
        if not _fetch_plan_disponible(sconn, pid, usuario_id):
            conn.run("UPDATE usuarios SET plan_solicitado_id = NULL WHERE id = :id", id=usuario_id)
    finally:
        sconn.close()


@router.put("/datos", response_model=OnboardingOut)
def guardar_datos(payload: OnboardingDatosIn, current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    conn = get_connection()
    try:
        if conn.run(
            "SELECT 1 FROM usuarios WHERE numero_documento = :d AND id <> :id",
            d=payload.numero_documento, id=current_user.id,
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese número de documento")

        conn.run("BEGIN")
        try:
            conn.run(
                "UPDATE usuarios SET numero_documento = :doc, telefono = :tel WHERE id = :id",
                doc=payload.numero_documento, tel=payload.telefono, id=current_user.id,
            )
            conn.run(
                """
                INSERT INTO negocios (usuario_id, nombre, tipo, rut, direccion, ciudad, telefono, sitio_web, moneda)
                VALUES (:uid, :nombre, :tipo, :rut, :direccion, :ciudad, :telefono, :sitio_web, :moneda)
                ON CONFLICT (usuario_id) DO UPDATE SET
                    nombre = EXCLUDED.nombre, tipo = EXCLUDED.tipo, rut = EXCLUDED.rut,
                    direccion = EXCLUDED.direccion, ciudad = EXCLUDED.ciudad, telefono = EXCLUDED.telefono,
                    sitio_web = EXCLUDED.sitio_web, moneda = EXCLUDED.moneda, updated_at = now()
                """,
                uid=current_user.id, nombre=payload.nombre_negocio, tipo=payload.tipo_negocio, rut=payload.rut,
                direccion=payload.direccion, ciudad=payload.ciudad, telefono=payload.telefono,
                sitio_web=payload.sitio_web, moneda=moneda_de_cuenta(current_user.id),
            )
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        _descartar_plan_no_disponible(conn, current_user.id)
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


@router.put("/logo", response_model=OnboardingOut)
def guardar_logo(payload: OnboardingLogoIn, current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    if payload.logo_url is not None and not LOGO_DATA_URL.match(payload.logo_url):
        raise HTTPException(status_code=422, detail="El logo debe ser una imagen PNG, JPG, WEBP, GIF o SVG")
    conn = get_connection()
    try:
        conn.run(
            "INSERT INTO negocios (usuario_id, logo_url) VALUES (:uid, :logo) "
            "ON CONFLICT (usuario_id) DO UPDATE SET logo_url = EXCLUDED.logo_url, updated_at = now()",
            uid=current_user.id, logo=payload.logo_url,
        )
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


@router.get("/planes", response_model=list[PlanPublicoOut])
def planes(current_user: UserOut = Depends(get_current_user_any_status)):
    conn = get_connection()
    try:
        seleccionado = conn.run("SELECT plan_solicitado_id FROM usuarios WHERE id = :id", id=current_user.id)[0][0]
    finally:
        conn.close()
    return listar_planes_disponibles(current_user.id, seleccionado)


@router.put("/plan", response_model=OnboardingOut)
def guardar_plan(payload: OnboardingPlanIn, current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    try:
        sconn = get_superadmin_connection()
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo verificar el plan")
    try:
        if not _fetch_plan_disponible(sconn, payload.plan_id, current_user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ese plan no está disponible")
    finally:
        sconn.close()

    conn = get_connection()
    try:
        conn.run("UPDATE usuarios SET plan_solicitado_id = :pid WHERE id = :id", pid=payload.plan_id, id=current_user.id)
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


@router.post("/documentos", response_model=OnboardingOut, status_code=status.HTTP_201_CREATED)
def subir_documento(payload: OnboardingDocumentoIn, current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    try:
        contenido = base64.b64decode(payload.contenido_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="El archivo no es válido")
    if len(contenido) > MAX_DOC_BYTES:
        raise HTTPException(status_code=422, detail="Cada documento puede pesar máximo 5 MB")
    content_type = _tipo_de_archivo(contenido)
    if content_type is None:
        raise HTTPException(status_code=422, detail="Solo se permiten archivos PDF, JPG o PNG")

    conn = get_connection()
    try:
        conn.run("BEGIN")
        try:
            if payload.tipo == "otro":
                if conn.run(
                    "SELECT count(*) FROM comercio_documentos WHERE usuario_id = :id", id=current_user.id,
                )[0][0] >= MAX_DOCS:
                    raise HTTPException(status_code=422, detail=f"Puedes cargar máximo {MAX_DOCS} documentos")
            else:
                conn.run(
                    "DELETE FROM comercio_documentos WHERE usuario_id = :id AND tipo = :tipo",
                    id=current_user.id, tipo=payload.tipo,
                )
            conn.run(
                "INSERT INTO comercio_documentos (usuario_id, tipo, nombre_archivo, content_type, tamano, contenido) "
                "VALUES (:uid, :tipo, :nombre, :ct, :tamano, :contenido)",
                uid=current_user.id, tipo=payload.tipo, nombre=payload.nombre_archivo.strip()[:200],
                ct=content_type, tamano=len(contenido), contenido=contenido,
            )
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


@router.delete("/documentos/{documento_id}", response_model=OnboardingOut)
def eliminar_documento(documento_id: int, current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM comercio_documentos WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=documento_id, uid=current_user.id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()


@router.post("/enviar", response_model=OnboardingOut)
def enviar(current_user: UserOut = Depends(get_current_user_any_status)):
    _require_editable(current_user)
    conn = get_connection()
    try:
        estado = _estado_completo(conn, current_user.id)
        faltantes = []
        if not all([
            estado.numero_documento, estado.telefono, estado.nombre_negocio, estado.rut, estado.direccion, estado.ciudad,
        ]):
            faltantes.append("Datos del comercio")
        if estado.plan_solicitado_id is None:
            faltantes.append("Selección del plan")
        # Los documentos (REQUIRED_DOCS) ya no bloquean el envío: el comercio puede omitirlos y
        # cargarlos después si el SuperAdmin los pide al revisar la solicitud.
        if faltantes:
            raise HTTPException(status_code=422, detail="Para enviar tu solicitud falta: " + ", ".join(faltantes))
        rechazados = [DOC_LABELS[d.tipo] for d in estado.documentos if d.estado == "rechazado"]
        if rechazados:
            raise HTTPException(
                status_code=422,
                detail="Reemplaza los documentos rechazados antes de reenviar: " + ", ".join(rechazados),
            )

        updated = conn.run(
            "UPDATE usuarios SET estado_aprobacion = 'pendiente_aprobacion', motivo_rechazo = '' "
            "WHERE id = :id AND estado_aprobacion IN ('pendiente_datos', 'rechazado') RETURNING id",
            id=current_user.id,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tu solicitud ya fue enviada")
        return _estado_completo(conn, current_user.id)
    finally:
        conn.close()
