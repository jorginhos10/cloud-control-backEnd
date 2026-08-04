import json
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    CierreZMesOut,
    CierreZOut,
    CierreZPreviewOut,
    CierreZResumenOut,
    ReporteXGeneralOut,
    ReporteXHoraOut,
    ReporteXOut,
    ReporteXProductoOut,
)

router = APIRouter(prefix="/reportes", dependencies=[Depends(get_current_user)])


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
    general = conn.run(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas "
        "WHERE usuario_id = :uid AND estado = 'cerrada' AND fecha_cierre BETWEEN :desde AND :hasta",
        uid=usuario_id, desde=desde, hasta=hasta,
    )[0]

    productos = conn.run(
        "SELECT vi.receta_id, vi.nombre, COALESCE(rc.label, 'Otro') AS categoria, "
        "SUM(vi.cantidad) AS cant, SUM(vi.subtotal) AS monto "
        "FROM venta_items vi "
        "JOIN ventas v ON v.id = vi.venta_id "
        "LEFT JOIN recetas r ON r.id = vi.receta_id "
        "LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id "
        "WHERE v.usuario_id = :uid AND v.estado = 'cerrada' AND v.fecha_cierre BETWEEN :desde AND :hasta "
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
    ultimo = conn.run(
        "SELECT fecha_hasta FROM cierres_z WHERE usuario_id = :uid ORDER BY fecha_hasta DESC LIMIT 1",
        uid=usuario_id,
    )
    hoy_medianoche = datetime.combine(date.today(), time.min)
    if ultimo and ultimo[0][0] >= hoy_medianoche:
        return ultimo[0][0]
    return hoy_medianoche


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


@router.post("/z/generar", response_model=CierreZOut, status_code=status.HTTP_201_CREATED)
def generar_cierre_z(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        desde = _fecha_desde_pendiente(conn, current_user.tenant_id)
        hasta = datetime.now()
        total_ventas, total_monto, por_producto = _calcular_periodo(conn, current_user.tenant_id, desde, hasta)
        if total_ventas == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No hay ventas nuevas para cerrar"
            )

        numero = conn.run(
            "SELECT COALESCE(MAX(numero_z), 0) + 1 FROM cierres_z WHERE usuario_id = :uid", uid=current_user.tenant_id
        )[0][0]

        datos_json = json.dumps({"por_producto": [p.model_dump() for p in por_producto]})
        rows = conn.run(
            "INSERT INTO cierres_z "
            "(usuario_id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, datos_json) "
            "VALUES (:uid, :num, :desde, :hasta, :tv, :tm, :datos) "
            "RETURNING id, numero_z, fecha_desde, fecha_hasta, total_ventas, total_monto, created_at",
            uid=current_user.tenant_id, num=numero, desde=desde, hasta=hasta,
            tv=total_ventas, tm=total_monto, datos=datos_json,
        )
        r = rows[0]
        return CierreZOut(
            id=r[0], numero_z=r[1], fecha_desde=r[2], fecha_hasta=r[3],
            total_ventas=r[4], total_monto=float(r[5]), por_producto=por_producto, created_at=r[6],
        )
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
