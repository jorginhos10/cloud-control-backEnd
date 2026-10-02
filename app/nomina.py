import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user, require_roles
from app.database import get_connection
from app.schemas import (
    CortePagoIn,
    CortePagoOut,
    CorteDiaOut,
    NominaCalcularIn,
    NominaDetalleOut,
    NominaDetalleUpdateIn,
    NominaEmpleadoIn,
    NominaEmpleadoOut,
    NominaPeriodoIn,
    NominaPeriodoOut,
)

# La nómina es información sensible (salarios, cuentas bancarias): solo el propietario o
# un staff con rol "admin" puede verla o tocarla, nunca mesero/cocina/inventario.
router = APIRouter(prefix="/nomina", dependencies=[Depends(require_roles("admin"))])

DAY_KEYS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]

PERFIL_COLUMNS = [
    "staff_id", "tipo_contrato", "tipo_pago", "salario_base", "valor_hora", "valor_dia",
    "eps", "afp", "arl", "fecha_ingreso", "banco", "tipo_cuenta", "numero_cuenta", "horario",
]

DETALLE_SELECT = (
    "SELECT d.id, d.periodo_id, d.staff_id, d.nombre_snapshot, d.salario_base, d.dias_trabajados, "
    "d.horas_extra, d.bonificaciones, d.propinas, d.otros_descuentos, d.salud, d.pension, "
    "d.total_devengado, d.total_deducciones, d.neto_pagar, d.notas, u.rol "
    "FROM nomina_detalle d JOIN usuarios u ON u.id = d.staff_id "
)


def _dia_key(d: date) -> str:
    return DAY_KEYS[d.isoweekday() - 1]


def _parse_horario(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw or {}


def _perfil_defaults(staff_id: int) -> dict:
    return {
        "staff_id": staff_id, "tipo_contrato": "indefinido", "tipo_pago": "mensual",
        "salario_base": 0, "valor_hora": 0, "valor_dia": 0, "eps": "", "afp": "", "arl": "",
        "fecha_ingreso": None, "banco": "", "tipo_cuenta": None, "numero_cuenta": "", "horario": {},
    }


def _detalle_out(r) -> NominaDetalleOut:
    return NominaDetalleOut(
        id=r[0], periodo_id=r[1], staff_id=r[2], nombre=r[3], salario_base=float(r[4]),
        dias_trabajados=float(r[5]), horas_extra=float(r[6]), bonificaciones=float(r[7]),
        propinas=float(r[8]), otros_descuentos=float(r[9]), salud=float(r[10]), pension=float(r[11]),
        total_devengado=float(r[12]), total_deducciones=float(r[13]), neto_pagar=float(r[14]),
        notas=r[15], rol=r[16],
    )


def _staff_or_404(conn, tenant_id: int, staff_id: int) -> dict:
    rows = conn.run(
        "SELECT id, nombre, apellido, rol, activo, numero_documento FROM usuarios "
        "WHERE id = :id AND (id = :tid OR propietario_id = :tid)",
        id=staff_id, tid=tenant_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empleado no encontrado")
    cols = ["id", "nombre", "apellido", "rol", "activo", "numero_documento"]
    return dict(zip(cols, rows[0]))


def _empleado_out(staff: dict, perfil: dict, tiene_perfil: bool) -> NominaEmpleadoOut:
    return NominaEmpleadoOut(
        staff_id=staff["id"], nombre=staff["nombre"], apellido=staff["apellido"] or "",
        rol=staff["rol"], activo=staff["activo"], numero_documento=staff["numero_documento"] or "",
        tiene_perfil=tiene_perfil, tipo_contrato=perfil["tipo_contrato"], tipo_pago=perfil["tipo_pago"],
        salario_base=float(perfil["salario_base"]), valor_hora=float(perfil["valor_hora"]),
        valor_dia=float(perfil["valor_dia"]), eps=perfil["eps"], afp=perfil["afp"], arl=perfil["arl"],
        fecha_ingreso=perfil["fecha_ingreso"], banco=perfil["banco"], tipo_cuenta=perfil["tipo_cuenta"],
        numero_cuenta=perfil["numero_cuenta"], horario=_parse_horario(perfil["horario"]),
    )


def _periodo_or_404(conn, tenant_id: int, periodo_id: int) -> str:
    """Devuelve el estado del periodo, o 404 si no existe o no es de este tenant."""
    rows = conn.run(
        "SELECT estado FROM nomina_periodos WHERE id = :id AND usuario_id = :uid",
        id=periodo_id, uid=tenant_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodo no encontrado")
    return rows[0][0]


def _periodo_out(conn, tenant_id: int, periodo_id: int) -> NominaPeriodoOut:
    row = conn.run(
        "SELECT id, fecha_inicio, fecha_fin, tipo, estado, created_at, cerrado_en "
        "FROM nomina_periodos WHERE id = :id AND usuario_id = :uid",
        id=periodo_id, uid=tenant_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodo no encontrado")
    r = row[0]
    resumen = conn.run(
        "SELECT COUNT(*), COALESCE(SUM(neto_pagar), 0) FROM nomina_detalle WHERE periodo_id = :id", id=periodo_id,
    )[0]
    return NominaPeriodoOut(
        id=r[0], fecha_inicio=r[1], fecha_fin=r[2], tipo=r[3], estado=r[4],
        created_at=r[5], cerrado_en=r[6], total_empleados=resumen[0], total_neto=float(resumen[1]),
    )


# ---------- Empleados (perfil de pago) ----------


@router.get("/empleados", response_model=list[NominaEmpleadoOut])
def list_empleados(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        staff_rows = conn.run(
            "SELECT id, nombre, apellido, rol, activo, numero_documento FROM usuarios "
            "WHERE id = :tid OR propietario_id = :tid ORDER BY propietario DESC, nombre",
            tid=current_user.tenant_id,
        )
        perfiles_rows = conn.run(
            f"SELECT {', '.join(PERFIL_COLUMNS)} FROM nomina_empleados WHERE usuario_id = :tid",
            tid=current_user.tenant_id,
        )
        perfiles = {r[0]: dict(zip(PERFIL_COLUMNS, r)) for r in perfiles_rows}
        staff_cols = ["id", "nombre", "apellido", "rol", "activo", "numero_documento"]
        return [
            _empleado_out(dict(zip(staff_cols, r)), perfiles.get(r[0]) or _perfil_defaults(r[0]), r[0] in perfiles)
            for r in staff_rows
        ]
    finally:
        conn.close()


@router.put("/empleados/{staff_id}", response_model=NominaEmpleadoOut)
def guardar_perfil(staff_id: int, payload: NominaEmpleadoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        staff = _staff_or_404(conn, current_user.tenant_id, staff_id)
        horario_json = json.dumps({k: v.model_dump() for k, v in payload.horario.items()})
        conn.run(
            "INSERT INTO nomina_empleados (usuario_id, staff_id, tipo_contrato, tipo_pago, salario_base, "
            "valor_hora, valor_dia, eps, afp, arl, fecha_ingreso, banco, tipo_cuenta, numero_cuenta, horario) "
            "VALUES (:uid, :sid, :tipo_contrato, :tipo_pago, :salario_base, :valor_hora, :valor_dia, :eps, :afp, "
            ":arl, :fecha_ingreso, :banco, :tipo_cuenta, :numero_cuenta, :horario) "
            "ON CONFLICT (usuario_id, staff_id) DO UPDATE SET "
            "tipo_contrato = EXCLUDED.tipo_contrato, tipo_pago = EXCLUDED.tipo_pago, "
            "salario_base = EXCLUDED.salario_base, valor_hora = EXCLUDED.valor_hora, valor_dia = EXCLUDED.valor_dia, "
            "eps = EXCLUDED.eps, afp = EXCLUDED.afp, arl = EXCLUDED.arl, "
            "fecha_ingreso = EXCLUDED.fecha_ingreso, banco = EXCLUDED.banco, "
            "tipo_cuenta = EXCLUDED.tipo_cuenta, numero_cuenta = EXCLUDED.numero_cuenta, "
            "horario = EXCLUDED.horario, updated_at = now()",
            uid=current_user.tenant_id, sid=staff_id,
            tipo_contrato=payload.tipo_contrato, tipo_pago=payload.tipo_pago,
            salario_base=payload.salario_base, valor_hora=payload.valor_hora, valor_dia=payload.valor_dia,
            eps=payload.eps.strip(), afp=payload.afp.strip(), arl=payload.arl.strip(),
            fecha_ingreso=payload.fecha_ingreso, banco=payload.banco.strip(),
            tipo_cuenta=payload.tipo_cuenta, numero_cuenta=payload.numero_cuenta.strip(), horario=horario_json,
        )
        perfil = {
            "tipo_contrato": payload.tipo_contrato, "tipo_pago": payload.tipo_pago,
            "salario_base": payload.salario_base, "valor_hora": payload.valor_hora, "valor_dia": payload.valor_dia,
            "eps": payload.eps.strip(), "afp": payload.afp.strip(), "arl": payload.arl.strip(),
            "fecha_ingreso": payload.fecha_ingreso, "banco": payload.banco.strip(),
            "tipo_cuenta": payload.tipo_cuenta, "numero_cuenta": payload.numero_cuenta.strip(),
            "horario": {k: v.model_dump() for k, v in payload.horario.items()},
        }
        return _empleado_out(staff, perfil, True)
    finally:
        conn.close()


# ---------- Periodos ----------


@router.get("/periodos", response_model=list[NominaPeriodoOut])
def list_periodos(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        ids = conn.run(
            "SELECT id FROM nomina_periodos WHERE usuario_id = :uid ORDER BY fecha_inicio DESC",
            uid=current_user.tenant_id,
        )
        return [_periodo_out(conn, current_user.tenant_id, r[0]) for r in ids]
    finally:
        conn.close()


@router.post("/periodos", response_model=NominaPeriodoOut, status_code=status.HTTP_201_CREATED)
def crear_periodo(payload: NominaPeriodoIn, current_user: UserOut = Depends(get_current_user)):
    if payload.fecha_fin < payload.fecha_inicio:
        raise HTTPException(status_code=422, detail="La fecha final no puede ser anterior a la fecha inicial")
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO nomina_periodos (usuario_id, fecha_inicio, fecha_fin, tipo) "
            "VALUES (:uid, :desde, :hasta, :tipo) RETURNING id",
            uid=current_user.tenant_id, desde=payload.fecha_inicio, hasta=payload.fecha_fin, tipo=payload.tipo,
        )
        return _periodo_out(conn, current_user.tenant_id, rows[0][0])
    finally:
        conn.close()


@router.delete("/periodos/{periodo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_periodo(periodo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        estado = _periodo_or_404(conn, current_user.tenant_id, periodo_id)
        if estado == "pagada":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No puedes eliminar un periodo ya pagado")
        conn.run("DELETE FROM nomina_periodos WHERE id = :id", id=periodo_id)
    finally:
        conn.close()


@router.get("/periodos/{periodo_id}/detalle", response_model=list[NominaDetalleOut])
def list_detalle(periodo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _periodo_or_404(conn, current_user.tenant_id, periodo_id)
        rows = conn.run(DETALLE_SELECT + "WHERE d.periodo_id = :id ORDER BY d.nombre_snapshot", id=periodo_id)
        return [_detalle_out(r) for r in rows]
    finally:
        conn.close()


def _dias_pagados_por_corte(conn, usuario_id: int, staff_id: int, desde: date, hasta: date) -> set:
    rows = conn.run(
        "SELECT fecha FROM nomina_pagos_diarios WHERE usuario_id = :uid AND staff_id = :sid "
        "AND fecha BETWEEN :desde AND :hasta",
        uid=usuario_id, sid=staff_id, desde=desde, hasta=hasta,
    )
    return {r[0] for r in rows}


def _dias_y_horas_programadas(horario: dict, desde: date, hasta: date, dias_excluidos: set) -> tuple[int, float]:
    """Cuenta cuántos días del rango caen en un día activo del horario, sin contar los que ya
    se pagaron por Corte diario (para no pagarlos dos veces), y la suma de horas programadas."""
    dias = 0
    horas = 0.0
    actual = desde
    while actual <= hasta:
        if actual not in dias_excluidos:
            info = horario.get(_dia_key(actual))
            if info and info.get("activo"):
                dias += 1
                horas += float(info.get("horas") or 0)
        actual += timedelta(days=1)
    return dias, horas


@router.post("/periodos/{periodo_id}/calcular", response_model=list[NominaDetalleOut])
def calcular_periodo(periodo_id: int, payload: NominaCalcularIn, current_user: UserOut = Depends(get_current_user)):
    """(Re)genera la liquidación del periodo. Los empleados mensuales/quincenales usan su salario base;
    los de pago por día u hora usan su horario semanal para saber cuántos días/horas del periodo les
    corresponde pagar. Puede repetirse mientras el periodo no esté pagado: cada llamada reemplaza el
    detalle anterior, así que los ajustes manuales que ya se hubieran guardado se pierden — el front
    avisa de esto antes de recalcular."""
    conn = get_connection()
    try:
        periodo = conn.run(
            "SELECT estado, fecha_inicio, fecha_fin FROM nomina_periodos WHERE id = :id AND usuario_id = :uid",
            id=periodo_id, uid=current_user.tenant_id,
        )
        if not periodo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Periodo no encontrado")
        estado, fecha_inicio, fecha_fin = periodo[0]
        if estado == "pagada":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este periodo ya fue pagado")

        empleados = conn.run(
            "SELECT u.id, u.nombre, u.apellido, e.tipo_pago, e.salario_base, e.valor_hora, e.valor_dia, e.horario "
            "FROM nomina_empleados e JOIN usuarios u ON u.id = e.staff_id WHERE e.usuario_id = :uid AND u.activo = true",
            uid=current_user.tenant_id,
        )
        if not empleados:
            raise HTTPException(
                status_code=422,
                detail="No hay empleados activos con perfil de nómina. Configúralos en la pestaña Empleados.",
            )

        conn.run("BEGIN")
        try:
            conn.run("DELETE FROM nomina_detalle WHERE periodo_id = :id", id=periodo_id)
            for sid, nombre, apellido, tipo_pago, salario_base, valor_hora, valor_dia, horario_raw in empleados:
                horario = _parse_horario(horario_raw)
                dias_excluidos = (
                    _dias_pagados_por_corte(conn, current_user.tenant_id, sid, fecha_inicio, fecha_fin)
                    if tipo_pago in ("por_dia", "por_horas")
                    else set()
                )
                dias_prog, horas_prog = _dias_y_horas_programadas(horario, fecha_inicio, fecha_fin, dias_excluidos)

                if tipo_pago == "por_dia":
                    dias_trabajados = float(dias_prog)
                    devengado_base = float(valor_dia) * dias_prog
                elif tipo_pago == "por_horas":
                    dias_trabajados = float(dias_prog)
                    devengado_base = float(valor_hora) * horas_prog
                else:
                    dias_trabajados = 30.0
                    devengado_base = float(salario_base)

                salud = round(devengado_base * payload.porcentaje_salud / 100, 2)
                pension = round(devengado_base * payload.porcentaje_pension / 100, 2)
                total_deducciones = salud + pension
                nombre_completo = f"{nombre} {apellido or ''}".strip()
                conn.run(
                    "INSERT INTO nomina_detalle (periodo_id, staff_id, nombre_snapshot, salario_base, "
                    "dias_trabajados, horas_extra, bonificaciones, propinas, otros_descuentos, salud, pension, "
                    "total_devengado, total_deducciones, neto_pagar) "
                    "VALUES (:pid, :sid, :nombre, :salario, :dias, 0, 0, 0, 0, :salud, :pension, :salario, :ded, :neto)",
                    pid=periodo_id, sid=sid, nombre=nombre_completo, salario=devengado_base, dias=dias_trabajados,
                    salud=salud, pension=pension, ded=total_deducciones, neto=devengado_base - total_deducciones,
                )
            conn.run("UPDATE nomina_periodos SET estado = 'calculada' WHERE id = :id", id=periodo_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise

        rows = conn.run(DETALLE_SELECT + "WHERE d.periodo_id = :id ORDER BY d.nombre_snapshot", id=periodo_id)
        return [_detalle_out(r) for r in rows]
    finally:
        conn.close()


@router.put("/periodos/{periodo_id}/detalle/{detalle_id}", response_model=NominaDetalleOut)
def actualizar_detalle(
    periodo_id: int, detalle_id: int, payload: NominaDetalleUpdateIn, current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        estado = _periodo_or_404(conn, current_user.tenant_id, periodo_id)
        if estado == "pagada":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este periodo ya fue pagado")

        actual = conn.run(
            "SELECT salario_base FROM nomina_detalle WHERE id = :id AND periodo_id = :pid",
            id=detalle_id, pid=periodo_id,
        )
        if not actual:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado")
        salario_base = float(actual[0][0])

        total_devengado = salario_base + payload.horas_extra + payload.bonificaciones + payload.propinas
        total_deducciones = payload.salud + payload.pension + payload.otros_descuentos

        conn.run(
            "UPDATE nomina_detalle SET dias_trabajados = :dias, horas_extra = :he, bonificaciones = :bon, "
            "propinas = :prop, otros_descuentos = :otros, salud = :salud, pension = :pension, "
            "total_devengado = :dev, total_deducciones = :ded, neto_pagar = :neto, notas = :notas WHERE id = :id",
            id=detalle_id, dias=payload.dias_trabajados, he=payload.horas_extra, bon=payload.bonificaciones,
            prop=payload.propinas, otros=payload.otros_descuentos, salud=payload.salud, pension=payload.pension,
            dev=total_devengado, ded=total_deducciones, neto=total_devengado - total_deducciones,
            notas=payload.notas.strip(),
        )
        rows = conn.run(DETALLE_SELECT + "WHERE d.id = :id", id=detalle_id)
        return _detalle_out(rows[0])
    finally:
        conn.close()


@router.post("/periodos/{periodo_id}/pagar", response_model=NominaPeriodoOut)
def pagar_periodo(periodo_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        estado = _periodo_or_404(conn, current_user.tenant_id, periodo_id)
        if estado != "calculada":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Primero debes calcular la nómina de este periodo")
        conn.run("UPDATE nomina_periodos SET estado = 'pagada', cerrado_en = now() WHERE id = :id", id=periodo_id)
        return _periodo_out(conn, current_user.tenant_id, periodo_id)
    finally:
        conn.close()


# ---------- Corte diario ----------
# Para el personal que se paga por día u hora: el horario dice quién trabaja hoy y cuánto se le debe,
# y "registrar el corte" deja constancia de que ya se le pagó ese día — sin pasar por un periodo formal.


@router.get("/corte", response_model=list[CorteDiaOut])
def corte_del_dia(fecha: date = Query(...), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        dia_key = _dia_key(fecha)
        empleados = conn.run(
            "SELECT u.id, u.nombre, u.apellido, u.rol, e.tipo_pago, e.valor_hora, e.valor_dia, e.horario "
            "FROM nomina_empleados e JOIN usuarios u ON u.id = e.staff_id "
            "WHERE e.usuario_id = :uid AND u.activo = true AND e.tipo_pago IN ('por_dia', 'por_horas')",
            uid=current_user.tenant_id,
        )
        pagos = {
            r[0]: r
            for r in conn.run(
                "SELECT staff_id, id, monto, notas FROM nomina_pagos_diarios WHERE usuario_id = :uid AND fecha = :f",
                uid=current_user.tenant_id, f=fecha,
            )
        }

        resultado = []
        for sid, nombre, apellido, rol, tipo_pago, valor_hora, valor_dia, horario_raw in empleados:
            horario = _parse_horario(horario_raw)
            info = horario.get(dia_key)
            if not info or not info.get("activo"):
                continue
            horas_prog = float(info.get("horas") or 0)
            monto_sugerido = float(valor_dia) if tipo_pago == "por_dia" else float(valor_hora) * horas_prog
            pago = pagos.get(sid)
            resultado.append(
                CorteDiaOut(
                    staff_id=sid, nombre=f"{nombre} {apellido or ''}".strip(), rol=rol, tipo_pago=tipo_pago,
                    horas_programadas=horas_prog, monto_sugerido=round(monto_sugerido, 2),
                    pago_id=pago[1] if pago else None, monto_pagado=float(pago[2]) if pago else None,
                    notas=pago[3] if pago else "",
                )
            )
        return resultado
    finally:
        conn.close()


@router.post("/corte", response_model=CortePagoOut)
def registrar_corte(payload: CortePagoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        staff = _staff_or_404(conn, current_user.tenant_id, payload.staff_id)
        ya_pagado = conn.run(
            "SELECT 1 FROM nomina_detalle d JOIN nomina_periodos p ON p.id = d.periodo_id "
            "WHERE d.staff_id = :sid AND p.usuario_id = :uid AND p.estado = 'pagada' "
            "AND :fecha BETWEEN p.fecha_inicio AND p.fecha_fin",
            sid=payload.staff_id, uid=current_user.tenant_id, fecha=payload.fecha,
        )
        if ya_pagado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este día ya quedó pagado dentro de un periodo de nómina. Revisa el historial de Liquidación.",
            )
        rows = conn.run(
            "INSERT INTO nomina_pagos_diarios (usuario_id, staff_id, fecha, monto, notas) "
            "VALUES (:uid, :sid, :fecha, :monto, :notas) "
            "ON CONFLICT (staff_id, fecha) DO UPDATE SET monto = EXCLUDED.monto, notas = EXCLUDED.notas "
            "RETURNING id, staff_id, fecha, monto, notas, created_at",
            uid=current_user.tenant_id, sid=payload.staff_id, fecha=payload.fecha,
            monto=payload.monto, notas=payload.notas.strip(),
        )
        r = rows[0]
        nombre = f"{staff['nombre']} {staff['apellido'] or ''}".strip()
        return CortePagoOut(id=r[0], staff_id=r[1], nombre=nombre, fecha=r[2], monto=float(r[3]), notas=r[4], created_at=r[5])
    finally:
        conn.close()


@router.delete("/corte/{pago_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_corte(pago_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM nomina_pagos_diarios WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=pago_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    finally:
        conn.close()


@router.get("/corte/historial", response_model=list[CortePagoOut])
def historial_cortes(
    desde: date = Query(...), hasta: date = Query(...), current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT p.id, p.staff_id, p.fecha, p.monto, p.notas, p.created_at, u.nombre, u.apellido "
            "FROM nomina_pagos_diarios p JOIN usuarios u ON u.id = p.staff_id "
            "WHERE p.usuario_id = :uid AND p.fecha BETWEEN :desde AND :hasta "
            "ORDER BY p.fecha DESC, u.nombre",
            uid=current_user.tenant_id, desde=desde, hasta=hasta,
        )
        return [
            CortePagoOut(
                id=r[0], staff_id=r[1], fecha=r[2], monto=float(r[3]), notas=r[4], created_at=r[5],
                nombre=f"{r[6]} {r[7] or ''}".strip(),
            )
            for r in rows
        ]
    finally:
        conn.close()
