import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user, require_roles
from app.database import get_connection
from app.schemas import (
    CierreAutomaticoIn,
    CierreAutomaticoOut,
    CierreZMesOut,
    CierreZOut,
    CierreZPreviewOut,
    CierreZResumenOut,
    ComparacionOut,
    ComparacionPeriodoOut,
    ReporteXGeneralOut,
    ReporteXHoraOut,
    ReporteXOut,
    ReporteXProductoOut,
    SerieBucketOut,
    SerieOut,
)

# Reportes financieros: solo propietario o staff "admin", nunca mesero/cocina/inventario.
router = APIRouter(prefix="/reportes", dependencies=[Depends(require_roles("admin"))])


@router.get("/x", response_model=ReporteXOut)
def reporte_x(fecha: date | None = Query(default=None), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        f = fecha or date.today()

        general = conn.run(
            "SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(AVG(total), 0) FROM ventas "
            "WHERE usuario_id = :uid AND estado = 'cerrada' AND fecha_cierre::date = :f",
            uid=current_user.tenant_id, f=f,
        )[0]

        total_platos = conn.run(
            "SELECT COALESCE(SUM(vi.cantidad), 0) FROM venta_items vi "
            "JOIN ventas v ON v.id = vi.venta_id "
            "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre::date = :f",
            uid=current_user.tenant_id, f=f,
        )[0][0]

        productos = conn.run(
            "SELECT vi.receta_id, vi.nombre, COALESCE(rc.label, 'Otro') AS categoria, "
            "SUM(vi.cantidad) AS cant, SUM(vi.subtotal) AS monto "
            "FROM venta_items vi "
            "JOIN ventas v ON v.id = vi.venta_id "
            "LEFT JOIN recetas r ON r.id = vi.receta_id "
            "LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id "
            "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre::date = :f "
            "GROUP BY vi.receta_id, vi.nombre, rc.label "
            "ORDER BY cant DESC LIMIT 20",
            uid=current_user.tenant_id, f=f,
        )

        horas = conn.run(
            "SELECT EXTRACT(HOUR FROM fecha_cierre)::int AS h, COUNT(*), COALESCE(SUM(total), 0) FROM ventas "
            "WHERE usuario_id = :uid AND estado = 'cerrada' AND fecha_cierre::date = :f "
            "GROUP BY h",
            uid=current_user.tenant_id, f=f,
        )
        por_hora_map = {r[0]: (r[1], float(r[2])) for r in horas}

        return ReporteXOut(
            fecha=f,
            general=ReporteXGeneralOut(
                total_ventas=general[0],
                total_monto=float(general[1]),
                ticket_promedio=float(general[2]),
                total_platos=total_platos,
            ),
            por_producto=[
                ReporteXProductoOut(
                    receta_id=r[0], nombre=r[1], categoria=r[2], cantidad=int(r[3]), monto=float(r[4])
                )
                for r in productos
            ],
            por_hora=[
                ReporteXHoraOut(hora=h, ventas=por_hora_map.get(h, (0, 0.0))[0], monto=por_hora_map.get(h, (0, 0.0))[1])
                for h in range(24)
            ],
        )
    finally:
        conn.close()


def _calcular_periodo(conn, usuario_id: int, desde: datetime, hasta: datetime):
    # El límite inferior es exclusivo a propósito: `hasta` de un cierre pasa a ser el `desde`
    # del siguiente, y con BETWEEN (inclusivo en ambos extremos) una venta justo en ese
    # instante se contaría en los dos cierres.
    general = conn.run(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas "
        "WHERE usuario_id = :uid AND estado = 'cerrada' AND fecha_cierre > :desde AND fecha_cierre <= :hasta",
        uid=usuario_id, desde=desde, hasta=hasta,
    )[0]

    productos = conn.run(
        "SELECT vi.receta_id, vi.nombre, COALESCE(rc.label, 'Otro') AS categoria, "
        "SUM(vi.cantidad) AS cant, SUM(vi.subtotal) AS monto "
        "FROM venta_items vi "
        "JOIN ventas v ON v.id = vi.venta_id "
        "LEFT JOIN recetas r ON r.id = vi.receta_id "
        "LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id "
        "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre > :desde AND v.fecha_cierre <= :hasta "
        "GROUP BY vi.receta_id, vi.nombre, rc.label "
        "ORDER BY cant DESC LIMIT 20",
        uid=usuario_id, desde=desde, hasta=hasta,
    )
    por_producto = [
        ReporteXProductoOut(receta_id=r[0], nombre=r[1], categoria=r[2], cantidad=int(r[3]), monto=float(r[4]))
        for r in productos
    ]
    return int(general[0]), float(general[1]), por_producto


def _fecha_desde_pendiente(conn, usuario_id: int) -> datetime:
    """Desde cuándo está pendiente de cerrar. Siempre es el `fecha_hasta` real del último
    cierre, sin importar qué tan viejo sea — si se salta un día sin generar el Z, esas
    ventas deben seguir apareciendo como pendientes, nunca desaparecer del reporte."""
    ultimo = conn.run(
        "SELECT fecha_hasta FROM cierres_z WHERE usuario_id = :uid ORDER BY fecha_hasta DESC LIMIT 1",
        uid=usuario_id,
    )
    if ultimo:
        return ultimo[0][0]
    return datetime.combine(date.today(), time.min)


@router.get("/z", response_model=list[CierreZResumenOut])
def listar_cierres_z(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, created_at "
            "FROM cierres_z WHERE usuario_id = :uid ORDER BY fecha_hasta DESC LIMIT 100",
            uid=current_user.tenant_id,
        )
        return [
            CierreZResumenOut(
                id=r[0], numero_z=r[1], fecha_desde=r[2], fecha_hasta=r[3],
                total_ventas=r[4], total_monto=float(r[5]), created_at=r[6],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/z/pendiente", response_model=CierreZPreviewOut)
def cierre_z_pendiente(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        desde = _fecha_desde_pendiente(conn, current_user.tenant_id)
        hasta = datetime.now()
        total_ventas, total_monto, por_producto = _calcular_periodo(conn, current_user.tenant_id, desde, hasta)
        return CierreZPreviewOut(
            fecha_desde=desde, fecha_hasta=hasta, total_ventas=total_ventas,
            total_monto=total_monto, por_producto=por_producto,
        )
    finally:
        conn.close()


@router.get("/z/grafica-mensual", response_model=list[CierreZMesOut])
def grafica_mensual_z(anio: int = Query(default=0), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        year = anio or date.today().year
        rows = conn.run(
            "SELECT EXTRACT(MONTH FROM fecha_hasta)::int AS mes, "
            "COALESCE(SUM(total_monto), 0), COALESCE(SUM(total_ventas), 0) "
            "FROM cierres_z WHERE usuario_id = :uid AND EXTRACT(YEAR FROM fecha_hasta) = :anio "
            "GROUP BY mes",
            uid=current_user.tenant_id, anio=year,
        )
        por_mes = {r[0]: (float(r[1]), int(r[2])) for r in rows}
        return [
            CierreZMesOut(mes=m, total_monto=por_mes.get(m, (0.0, 0))[0], total_ventas=por_mes.get(m, (0.0, 0))[1])
            for m in range(1, 13)
        ]
    finally:
        conn.close()


def generar_cierre(conn, usuario_id: int, automatico: bool = False) -> CierreZOut:
    """Núcleo de la generación de un cierre Z, compartido por el botón manual y por el
    scheduler del cierre automático (ver app/scheduler.py)."""
    desde = _fecha_desde_pendiente(conn, usuario_id)
    hasta = datetime.now()
    total_ventas, total_monto, por_producto = _calcular_periodo(conn, usuario_id, desde, hasta)

    numero = conn.run(
        "SELECT COALESCE(MAX(numero_z), 0) + 1 FROM cierres_z WHERE usuario_id = :uid", uid=usuario_id
    )[0][0]

    datos_json = json.dumps({"por_producto": [p.model_dump() for p in por_producto]})
    rows = conn.run(
        "INSERT INTO cierres_z "
        "(usuario_id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, datos_json, automatico) "
        "VALUES (:uid, :num, :desde, :hasta, :tv, :tm, :datos, :auto) "
        "RETURNING id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, created_at",
        uid=usuario_id, num=numero, desde=desde, hasta=hasta,
        tv=total_ventas, tm=total_monto, datos=datos_json, auto=automatico,
    )
    r = rows[0]
    return CierreZOut(
        id=r[0], numero_z=r[1], fecha_desde=r[2], fecha_hasta=r[3],
        total_ventas=r[4], total_monto=float(r[5]), por_producto=por_producto, created_at=r[6],
    )


@router.post("/z/generar", response_model=CierreZOut, status_code=status.HTTP_201_CREATED)
def generar_cierre_z(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return generar_cierre(conn, current_user.tenant_id, automatico=False)
    finally:
        conn.close()


@router.get("/z/automatico", response_model=CierreAutomaticoOut)
def get_cierre_automatico(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT cierre_automatico_activo, cierre_automatico_hora FROM negocios WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )
        if not rows:
            return CierreAutomaticoOut(activo=False, hora=23)
        return CierreAutomaticoOut(activo=rows[0][0], hora=rows[0][1])
    finally:
        conn.close()


@router.put("/z/automatico", response_model=CierreAutomaticoOut)
def set_cierre_automatico(payload: CierreAutomaticoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        conn.run(
            "UPDATE negocios SET cierre_automatico_activo = :activo, cierre_automatico_hora = :hora WHERE usuario_id = :uid",
            activo=payload.activo, hora=payload.hora, uid=current_user.tenant_id,
        )
        return CierreAutomaticoOut(activo=payload.activo, hora=payload.hora)
    finally:
        conn.close()


@router.get("/z/{cierre_id}", response_model=CierreZOut)
def get_cierre_z(cierre_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, datos_json, created_at "
            "FROM cierres_z WHERE id = :id AND usuario_id = :uid",
            id=cierre_id, uid=current_user.tenant_id,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cierre no encontrado")
        r = rows[0]
        datos = json.loads(r[6]) if r[6] else {"por_producto": []}
        por_producto = [ReporteXProductoOut(**p) for p in datos.get("por_producto", [])]
        return CierreZOut(
            id=r[0], numero_z=r[1], fecha_desde=r[2], fecha_hasta=r[3],
            total_ventas=r[4], total_monto=float(r[5]), por_producto=por_producto, created_at=r[7],
        )
    finally:
        conn.close()


# --- Reportes avanzados: series y comparaciones por rango de fechas -----------------------------

_UNIDAD = {"dia": "day", "semana": "week", "mes": "month"}
_MAX_BUCKETS = 400


@router.get("/serie", response_model=SerieOut)
def serie_ventas(
    granularidad: str = Query(default="dia"),
    desde: date = Query(),
    hasta: date = Query(),
    current_user: UserOut = Depends(get_current_user),
):
    """Ventas cerradas agrupadas por día, semana (lunes a domingo) o mes; los periodos sin ventas salen en cero."""
    unidad = _UNIDAD.get(granularidad)
    if unidad is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Granularidad inválida")
    if hasta < desde:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha final es anterior a la inicial")
    dias = (hasta - desde).days + 1
    if dias > 800:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El rango no puede superar 800 días")

    conn = get_connection()
    try:
        # `unidad` sale de una lista fija, no del usuario, así que es seguro interpolarla.
        rows = conn.run(
            f"SELECT g.d::date, COUNT(v.id), COALESCE(SUM(v.total), 0), COALESCE(SUM(v.propina), 0) "
            f"FROM generate_series(date_trunc('{unidad}', CAST(:desde AS timestamp)), "
            f"CAST(:hasta AS timestamp), interval '1 {unidad}') AS g(d) "
            f"LEFT JOIN ventas v ON v.usuario_id = :uid AND v.estado = 'cerrada' "
            f"AND v.fecha_cierre >= g.d AND v.fecha_cierre < g.d + interval '1 {unidad}' "
            f"GROUP BY g.d ORDER BY g.d",
            uid=current_user.tenant_id, desde=desde, hasta=hasta,
        )
        if len(rows) > _MAX_BUCKETS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Demasiados periodos; acorta el rango")
        return SerieOut(
            granularidad=granularidad,
            buckets=[
                SerieBucketOut(
                    inicio=r[0], ventas=int(r[1]), monto=float(r[2]), propinas=float(r[3]),
                    ticket_promedio=float(r[2]) / int(r[1]) if r[1] else 0.0,
                )
                for r in rows
            ],
        )
    finally:
        conn.close()


def _resumen_rango(conn, usuario_id: int, desde: date, hasta: date) -> ComparacionPeriodoOut:
    # `hasta` es un día completo: se compara contra el inicio del día siguiente.
    ini = datetime.combine(desde, time.min)
    fin = datetime.combine(hasta, time.min) + timedelta(days=1)
    g = conn.run(
        "SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(SUM(propina), 0) FROM ventas "
        "WHERE usuario_id = :uid AND estado = 'cerrada' AND fecha_cierre >= :ini AND fecha_cierre < :fin",
        uid=usuario_id, ini=ini, fin=fin,
    )[0]
    platos = conn.run(
        "SELECT COALESCE(SUM(vi.cantidad), 0) FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id "
        "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre >= :ini AND v.fecha_cierre < :fin",
        uid=usuario_id, ini=ini, fin=fin,
    )[0][0]
    prods = conn.run(
        "SELECT vi.receta_id, vi.nombre, COALESCE(rc.label, 'Otro'), SUM(vi.cantidad), SUM(vi.subtotal) "
        "FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id "
        "LEFT JOIN recetas r ON r.id = vi.receta_id LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id "
        "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre >= :ini AND v.fecha_cierre < :fin "
        "GROUP BY vi.receta_id, vi.nombre, rc.label ORDER BY SUM(vi.cantidad) DESC LIMIT 5",
        uid=usuario_id, ini=ini, fin=fin,
    )
    ventas = int(g[0])
    return ComparacionPeriodoOut(
        desde=desde, hasta=hasta, ventas=ventas, monto=float(g[1]), propinas=float(g[2]),
        ticket_promedio=float(g[1]) / ventas if ventas else 0.0, platos=int(platos),
        top_productos=[
            ReporteXProductoOut(receta_id=p[0], nombre=p[1], categoria=p[2], cantidad=int(p[3]), monto=float(p[4]))
            for p in prods
        ],
    )


@router.get("/comparar", response_model=ComparacionOut)
def comparar_periodos(
    a_desde: date = Query(),
    a_hasta: date = Query(),
    b_desde: date = Query(),
    b_hasta: date = Query(),
    current_user: UserOut = Depends(get_current_user),
):
    """Totales y top de productos de dos rangos de fechas, para ponerlos lado a lado."""
    if a_hasta < a_desde or b_hasta < b_desde:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha final es anterior a la inicial")
    if (a_hasta - a_desde).days > 800 or (b_hasta - b_desde).days > 800:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El rango no puede superar 800 días")
    conn = get_connection()
    try:
        return ComparacionOut(
            a=_resumen_rango(conn, current_user.tenant_id, a_desde, a_hasta),
            b=_resumen_rango(conn, current_user.tenant_id, b_desde, b_hasta),
        )
    finally:
        conn.close()
