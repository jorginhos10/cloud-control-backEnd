from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import FacturacionElectronicaIn, FacturacionElectronicaOut

router = APIRouter(
    prefix="/facturacion-electronica",
    tags=["facturacion-electronica"],
    dependencies=[Depends(get_current_user)],
)

EDIT_COLUMNS = [
    "activa", "ambiente", "tipo_documento",
    "tipo_persona", "nit", "razon_social", "nombre_comercial", "regimen_iva", "responsabilidades_fiscales",
    "actividad_economica", "matricula_mercantil", "direccion", "departamento", "ciudad", "codigo_municipio",
    "codigo_postal", "telefono", "email_facturacion",
    "resolucion_numero", "resolucion_fecha", "prefijo", "rango_desde", "rango_hasta", "vigencia_desde",
    "vigencia_hasta",
    "proveedor_tecnologico", "usuario_api", "software_id", "test_set_id", "enviar_email_cliente",
]
SECRET_COLUMNS = ["clave_tecnica", "token_api", "software_pin"]
WRITE_COLUMNS = EDIT_COLUMNS + ["dv"] + SECRET_COLUMNS
READ_COLUMNS = WRITE_COLUMNS + ["updated_at"]

_DV_WEIGHTS = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def calcular_dv(nit: str) -> str:
    if not nit:
        return ""
    total = sum(int(digit) * weight for digit, weight in zip(reversed(nit), _DV_WEIGHTS))
    remainder = total % 11
    return str(remainder if remainder < 2 else 11 - remainder)


def _require_propietario(current_user: UserOut) -> None:
    if not current_user.propietario:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el propietario puede gestionar la facturación electrónica",
        )


def _row_to_out(row) -> FacturacionElectronicaOut:
    data = dict(zip(READ_COLUMNS, row))
    data["responsabilidades_fiscales"] = [r for r in data["responsabilidades_fiscales"].split(",") if r]
    secrets_set = {col: bool(data.pop(col)) for col in SECRET_COLUMNS}
    return FacturacionElectronicaOut(
        **data,
        clave_tecnica_configurada=secrets_set["clave_tecnica"],
        token_api_configurado=secrets_set["token_api"],
        software_pin_configurado=secrets_set["software_pin"],
    )


def _validar(payload: FacturacionElectronicaIn, secretos: dict[str, str]) -> None:
    if payload.rango_desde and payload.rango_hasta and payload.rango_desde > payload.rango_hasta:
        raise HTTPException(status_code=422, detail="El rango de numeración 'desde' no puede ser mayor que 'hasta'")
    if payload.vigencia_desde and payload.vigencia_hasta and payload.vigencia_desde > payload.vigencia_hasta:
        raise HTTPException(status_code=422, detail="La vigencia 'desde' no puede ser posterior a 'hasta'")

    if not payload.activa:
        return

    faltantes = [
        etiqueta
        for etiqueta, valor in [
            ("NIT", payload.nit),
            ("Razón social", payload.razon_social.strip()),
            ("Responsabilidades fiscales", payload.responsabilidades_fiscales),
            ("Dirección", payload.direccion.strip()),
            ("Código DANE del municipio", payload.codigo_municipio),
            ("Correo de facturación", payload.email_facturacion),
            ("Número de resolución", payload.resolucion_numero.strip()),
            ("Fecha de la resolución", payload.resolucion_fecha),
            ("Rango desde", payload.rango_desde),
            ("Rango hasta", payload.rango_hasta),
            ("Vigencia desde", payload.vigencia_desde),
            ("Vigencia hasta", payload.vigencia_hasta),
        ]
        if not valor
    ]

    if payload.proveedor_tecnologico.strip():
        if not secretos["token_api"]:
            faltantes.append("Token / API key del proveedor")
    else:
        if not payload.software_id.strip():
            faltantes.append("ID del software")
        if not secretos["software_pin"]:
            faltantes.append("PIN del software")
        if not secretos["clave_tecnica"]:
            faltantes.append("Clave técnica")
        if payload.ambiente == "habilitacion" and not payload.test_set_id.strip():
            faltantes.append("ID del set de pruebas (TestSetId)")

    if faltantes:
        raise HTTPException(
            status_code=422,
            detail="Para activar la facturación electrónica falta: " + ", ".join(faltantes),
        )
    if payload.vigencia_hasta < date.today():
        raise HTTPException(status_code=422, detail="La resolución de numeración está vencida")


@router.get("", response_model=FacturacionElectronicaOut)
def obtener(current_user: UserOut = Depends(get_current_user)):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(READ_COLUMNS)} FROM facturacion_electronica WHERE usuario_id = :id",
            id=current_user.tenant_id,
        )
        if not rows:
            return FacturacionElectronicaOut()
        return _row_to_out(rows[0])
    finally:
        conn.close()


@router.put("", response_model=FacturacionElectronicaOut)
def guardar(payload: FacturacionElectronicaIn, current_user: UserOut = Depends(get_current_user)):
    _require_propietario(current_user)
    conn = get_connection()
    try:
        existentes = conn.run(
            f"SELECT {', '.join(SECRET_COLUMNS)} FROM facturacion_electronica WHERE usuario_id = :id",
            id=current_user.tenant_id,
        )
        guardados = dict(zip(SECRET_COLUMNS, existentes[0])) if existentes else {c: "" for c in SECRET_COLUMNS}
        secretos = {c: getattr(payload, c) or guardados[c] for c in SECRET_COLUMNS}

        _validar(payload, secretos)

        params: dict = {}
        for col in EDIT_COLUMNS:
            value = getattr(payload, col)
            if col == "responsabilidades_fiscales":
                value = ",".join(value)
            elif isinstance(value, str):
                value = value.strip()
            params[col] = value
        params["dv"] = calcular_dv(payload.nit)
        for col in SECRET_COLUMNS:
            params[col] = getattr(payload, col).strip()

        secret_updates = ", ".join(
            f"{c} = CASE WHEN EXCLUDED.{c} = '' THEN facturacion_electronica.{c} ELSE EXCLUDED.{c} END"
            for c in SECRET_COLUMNS
        )
        plain_updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in EDIT_COLUMNS + ["dv"])
        rows = conn.run(
            f"""
            INSERT INTO facturacion_electronica (usuario_id, {', '.join(WRITE_COLUMNS)})
            VALUES (:uid, {', '.join(':' + c for c in WRITE_COLUMNS)})
            ON CONFLICT (usuario_id) DO UPDATE SET {plain_updates}, {secret_updates}, updated_at = now()
            RETURNING {', '.join(READ_COLUMNS)}
            """,
            uid=current_user.tenant_id,
            **params,
        )
        return _row_to_out(rows[0])
    finally:
        conn.close()
