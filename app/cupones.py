import re
import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pg8000.exceptions import DatabaseError

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import (
    CodigoDisponibleOut,
    CuponEstadisticasOut,
    CuponIn,
    CuponMesOut,
    CuponOut,
)

router = APIRouter(prefix="/cupones", dependencies=[Depends(get_current_user)])

UNIQUE_VIOLATION = "23505"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0,1,I,O para evitar confusiones

CUPON_COLUMNS = [
    "id", "codigo", "nombre", "tipo", "descuento", "usos_max",
    "usos_actual", "estado", "expira_en", "id_receta", "created_at",
]


def _row_to_cupon(row: dict) -> CuponOut:
    return CuponOut(
        id=row["id"],
        codigo=row["codigo"],
        nombre=row["nombre"] or "",
        tipo=row["tipo"],
        descuento=float(row["descuento"]),
        usos_max=row["usos_max"],
        usos_actual=row["usos_actual"],
        estado=row["estado"],
        expira_en=row["expira_en"].isoformat() if row["expira_en"] else None,
        id_receta=row["id_receta"],
        receta_nombre=None,
        created_at=row["created_at"],
    )


def _codigo_existe(conn, usuario_id: int, codigo: str) -> bool:
    return bool(conn.run("SELECT 1 FROM cupones WHERE usuario_id = :uid AND codigo = :c", uid=usuario_id, c=codigo))


def _generar_codigo(conn, usuario_id: int) -> str:
    while True:
        codigo = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not _codigo_existe(conn, usuario_id, codigo):
            return codigo


@router.get("", response_model=list[CuponOut])
def list_cupones(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            f"SELECT {', '.join(CUPON_COLUMNS)} FROM cupones WHERE usuario_id = :uid ORDER BY created_at DESC",
            uid=current_user.tenant_id,
        )
        return [_row_to_cupon(dict(zip(CUPON_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=CuponEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE estado = 'activo'), "
            "COUNT(*) FILTER (WHERE estado = 'usado'), "
            "COUNT(*) FILTER (WHERE estado = 'inactivo') "
            "FROM cupones WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return CuponEstadisticasOut(total=row[0], activos=row[1], usados=row[2], inactivos=row[3])
    finally:
        conn.close()


@router.get("/grafica-mensual", response_model=list[CuponMesOut])
def grafica_mensual(anio: int = Query(default=0), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        year = anio or date.today().year
        rows = conn.run(
            "SELECT EXTRACT(MONTH FROM cu.fecha_uso)::int AS mes, COUNT(*), COALESCE(SUM(cu.monto_descuento), 0) "
            "FROM cupones_usos cu JOIN cupones c ON c.id = cu.id_cupon "
            "WHERE c.usuario_id = :uid AND EXTRACT(YEAR FROM cu.fecha_uso) = :anio GROUP BY mes",
            uid=current_user.tenant_id, anio=year,
        )
        por_mes = {r[0]: (r[1], float(r[2])) for r in rows}
        return [
            CuponMesOut(mes=m, usos=por_mes.get(m, (0, 0.0))[0], total=por_mes.get(m, (0, 0.0))[1])
            for m in range(1, 13)
        ]
    finally:
        conn.close()


@router.get("/verificar-codigo", response_model=CodigoDisponibleOut)
def verificar_codigo(codigo: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    codigo = re.sub(r"[^A-Za-z0-9]", "", codigo).upper()
    if len(codigo) < 3:
        return CodigoDisponibleOut(disponible=None)
    conn = get_connection()
    try:
        return CodigoDisponibleOut(disponible=not _codigo_existe(conn, current_user.tenant_id, codigo))
    finally:
        conn.close()


@router.post("", response_model=CuponOut, status_code=status.HTTP_201_CREATED)
def create_cupon(payload: CuponIn, current_user: UserOut = Depends(get_current_user)):
    if payload.tipo in ("porcentaje", "producto") and payload.descuento > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El porcentaje no puede superar 100")
    if payload.tipo == "producto" and not payload.id_receta:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debes seleccionar un producto")

    codigo_custom = re.sub(r"[^A-Za-z0-9]", "", payload.codigo).upper()
    if codigo_custom and not (3 <= len(codigo_custom) <= 8):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="El código debe tener entre 3 y 8 caracteres"
        )

    conn = get_connection()
    try:
        id_receta = None
        if payload.tipo == "producto" and payload.id_receta:
            existe = conn.run(
                "SELECT 1 FROM recetas WHERE id = :id AND usuario_id = :uid",
                id=payload.id_receta, uid=current_user.tenant_id,
            )
            if not existe:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La receta indicada no existe")
            id_receta = payload.id_receta

        if codigo_custom:
            if _codigo_existe(conn, current_user.tenant_id, codigo_custom):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese código ya existe, elige otro")
            codigo = codigo_custom
        else:
            codigo = _generar_codigo(conn, current_user.tenant_id)

        try:
            rows = conn.run(
                "INSERT INTO cupones (usuario_id, codigo, nombre, tipo, descuento, usos_max, expira_en, id_receta) "
                "VALUES (:uid, :codigo, :nombre, :tipo, :descuento, :usos_max, :expira_en, :id_receta) "
                f"RETURNING {', '.join(CUPON_COLUMNS)}",
                uid=current_user.tenant_id,
                codigo=codigo,
                nombre=payload.nombre.strip() or None,
                tipo=payload.tipo,
                descuento=payload.descuento,
                usos_max=payload.usos_max,
                expira_en=payload.expira_en or None,
                id_receta=id_receta,
            )
        except DatabaseError as exc:
            if exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese código ya existe, elige otro")
            raise

        return _row_to_cupon(dict(zip(CUPON_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{cupon_id}/toggle", response_model=CuponOut)
def toggle_cupon(cupon_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "SELECT estado FROM cupones WHERE id = :id AND usuario_id = :uid", id=cupon_id, uid=current_user.tenant_id
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cupón no encontrado")
        actual = rows[0][0]
        if actual == "usado":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes cambiar un cupón usado")
        nuevo = "inactivo" if actual == "activo" else "activo"
        updated = conn.run(
            f"UPDATE cupones SET estado = :e WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(CUPON_COLUMNS)}",
            e=nuevo,
            id=cupon_id,
            uid=current_user.tenant_id,
        )
        return _row_to_cupon(dict(zip(CUPON_COLUMNS, updated[0])))
    finally:
        conn.close()


@router.delete("/{cupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cupon(cupon_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM cupones WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=cupon_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cupón no encontrado")
    finally:
        conn.close()
