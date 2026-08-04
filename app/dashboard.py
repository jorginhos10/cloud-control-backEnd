from datetime import date

from fastapi import APIRouter, Depends, Query

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    DashboardCategoriaOut,
    DashboardProductoCantidadOut,
    DashboardProductoMontoOut,
    DashboardResumenOut,
    DashboardTotalesOut,
)

router = APIRouter(prefix="/dashboard", dependencies=[Depends(get_current_user)])


def _parse_int_list(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip() != ""]


def _in_clause(column: str, values: list[int], prefix: str, params: dict) -> str:
    keys = []
    for i, v in enumerate(values):
        key = f"{prefix}{i}"
        params[key] = v
        keys.append(f":{key}")
    return f"{column} IN ({', '.join(keys)})"


@router.get("/resumen", response_model=DashboardResumenOut)
def resumen(
    anio: int = Query(default=0),
    dias: str = Query(default=""),
    trimestres: str = Query(default=""),
    semestres: str = Query(default=""),
    meses: str = Query(default=""),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        year = anio or date.today().year

        clauses = ["v.usuario_id = :uid", "v.estado = 'cerrada'", "EXTRACT(YEAR FROM v.fecha_cierre) = :anio"]
        params: dict = {"uid": current_user.tenant_id, "anio": year}

        dias_list = _parse_int_list(dias)
        if dias_list:
            clauses.append(_in_clause("EXTRACT(DOW FROM v.fecha_cierre)::int", dias_list, "d", params))

        trims = _parse_int_list(trimestres)
        if trims:
            clauses.append(_in_clause("CEIL(EXTRACT(MONTH FROM v.fecha_cierre) / 3.0)::int", trims, "t", params))

        sems = _parse_int_list(semestres)
        if sems:
            clauses.append(
                _in_clause(
                    "(CASE WHEN EXTRACT(MONTH FROM v.fecha_cierre) <= 6 THEN 1 ELSE 2 END)", sems, "s", params
                )
            )

        meses_list = _parse_int_list(meses)
        if meses_list:
            clauses.append(_in_clause("EXTRACT(MONTH FROM v.fecha_cierre)::int", [m + 1 for m in meses_list], "m", params))

        where_sql = " AND ".join(clauses)

        totales_row = conn.run(
            f"SELECT COALESCE(SUM(v.total), 0), COALESCE(SUM(v.propina), 0) FROM ventas v WHERE {where_sql}",
            **params,
        )[0]
        ventas_total = float(totales_row[0])
        propinas_total = float(totales_row[1])

        costos_row = conn.run(
            "SELECT COALESCE(SUM(vi.cantidad * COALESCE(rc.costo, 0)), 0) "
            "FROM venta_items vi "
            "JOIN ventas v ON v.id = vi.venta_id "
            "LEFT JOIN ("
            "    SELECT ri.id_receta, SUM(ri.cantidad * i.precio_unitario) AS costo "
            "    FROM receta_insumos ri JOIN insumos i ON i.id = ri.id_insumo GROUP BY ri.id_receta"
            ") rc ON rc.id_receta = vi.receta_id "
            f"WHERE {where_sql}",
            **params,
        )[0]
        costos_total = float(costos_row[0])

        mes_rows = conn.run(
            f"SELECT EXTRACT(MONTH FROM v.fecha_cierre)::int - 1 AS mes_idx, COALESCE(SUM(v.total), 0) "
            f"FROM ventas v WHERE {where_sql} GROUP BY mes_idx",
            **params,
        )
        ventas_por_mes = [0.0] * 12
        for mes_idx, monto in mes_rows:
            ventas_por_mes[mes_idx] = float(monto)

        producto_rows = conn.run(
            "SELECT vi.nombre, COALESCE(SUM(vi.subtotal), 0) AS monto, COALESCE(SUM(vi.cantidad), 0) AS cantidad "
            "FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id "
            f"WHERE {where_sql} GROUP BY vi.nombre",
            **params,
        )
        productos = [(r[0], float(r[1]), int(r[2])) for r in producto_rows]
        top_productos = sorted(productos, key=lambda p: p[1], reverse=True)[:5]
        productos_mas_solicitados = sorted(productos, key=lambda p: p[2], reverse=True)[:8]

        categoria_rows = conn.run(
            "SELECT COALESCE(rc.label, 'Otro') AS categoria, COALESCE(SUM(vi.subtotal), 0) AS monto "
            "FROM venta_items vi "
            "JOIN ventas v ON v.id = vi.venta_id "
            "LEFT JOIN recetas r ON r.id = vi.receta_id "
            "LEFT JOIN receta_categorias rc ON rc.id = r.categoria_id "
            f"WHERE {where_sql} GROUP BY categoria ORDER BY monto DESC",
            **params,
        )

        return DashboardResumenOut(
            totales=DashboardTotalesOut(
                ventas=ventas_total, costos=costos_total, propinas=propinas_total,
                ganancias=round(ventas_total - costos_total, 2),
            ),
            ventas_por_mes=ventas_por_mes,
            top_productos=[DashboardProductoMontoOut(producto=p[0], monto=p[1]) for p in top_productos],
            productos_mas_solicitados=[
                DashboardProductoCantidadOut(producto=p[0], cantidad=p[2]) for p in productos_mas_solicitados
            ],
            ventas_por_categoria=[
                DashboardCategoriaOut(categoria=r[0], monto=float(r[1])) for r in categoria_rows
            ],
        )
    finally:
        conn.close()
