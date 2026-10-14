from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import GastoEstadisticasOut, GastoIn, GastoOut

router = APIRouter(prefix="/gastos", dependencies=[Depends(get_current_user)])

GASTO_COLUMNS = ["id", "concepto", "categoria", "monto", "fecha", "nota", "created_at"]


def _row_to_gasto(row: dict) -> GastoOut:
    return GastoOut(
        id=row["id"],
        concepto=row["concepto"],
        categoria=row["categoria"],
        monto=float(row["monto"]),
        fecha=row["fecha"],
        nota=row["nota"],
        created_at=row["created_at"],
    )


@router.get("", response_model=list[GastoOut])
def list_gastos(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                f"SELECT {', '.join(GASTO_COLUMNS)} FROM gastos "
                "WHERE usuario_id = :uid AND (concepto ILIKE :q OR categoria ILIKE :q OR nota ILIKE :q) "
                "ORDER BY fecha DESC, id DESC",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(GASTO_COLUMNS)} FROM gastos WHERE usuario_id = :uid ORDER BY fecha DESC, id DESC",
                uid=current_user.tenant_id,
            )
        return [_row_to_gasto(dict(zip(GASTO_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=GastoEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COALESCE(SUM(monto), 0), "
            "COALESCE(SUM(monto) FILTER (WHERE date_trunc('month', fecha) = date_trunc('month', CURRENT_DATE)), 0), "
            "COUNT(DISTINCT categoria) "
            "FROM gastos WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return GastoEstadisticasOut(
            total_registrados=row[0], total_monto=float(row[1]), mes_monto=float(row[2]), categorias=row[3],
        )
    finally:
        conn.close()


def _get_gasto_or_404(conn, usuario_id: int, gasto_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(GASTO_COLUMNS)} FROM gastos WHERE id = :id AND usuario_id = :uid",
        id=gasto_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    return dict(zip(GASTO_COLUMNS, rows[0]))


@router.post("", response_model=GastoOut, status_code=status.HTTP_201_CREATED)
def create_gasto(payload: GastoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO gastos (usuario_id, concepto, categoria, monto, fecha, nota) "
            "VALUES (:uid, :concepto, :categoria, :monto, :fecha, :nota) "
            f"RETURNING {', '.join(GASTO_COLUMNS)}",
            uid=current_user.tenant_id,
            concepto=payload.concepto.strip(),
            categoria=payload.categoria,
            monto=payload.monto,
            fecha=payload.fecha,
            nota=payload.nota.strip(),
        )
        return _row_to_gasto(dict(zip(GASTO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{gasto_id}", response_model=GastoOut)
def update_gasto(gasto_id: int, payload: GastoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_gasto_or_404(conn, current_user.tenant_id, gasto_id)
        rows = conn.run(
            "UPDATE gastos SET concepto = :concepto, categoria = :categoria, monto = :monto, "
            "fecha = :fecha, nota = :nota WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(GASTO_COLUMNS)}",
            id=gasto_id,
            uid=current_user.tenant_id,
            concepto=payload.concepto.strip(),
            categoria=payload.categoria,
            monto=payload.monto,
            fecha=payload.fecha,
            nota=payload.nota.strip(),
        )
        return _row_to_gasto(dict(zip(GASTO_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{gasto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gasto(gasto_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM gastos WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=gasto_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    finally:
        conn.close()
