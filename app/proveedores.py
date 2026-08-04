from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import ProveedorActivoIn, ProveedorEstadisticasOut, ProveedorIn, ProveedorOut

router = APIRouter(prefix="/proveedores", dependencies=[Depends(get_current_user)])

PROVEEDOR_COLUMNS = [
    "id", "nombre", "empresa", "telefono", "direccion", "correo",
    "categoria", "nit_rut", "observacion", "activo", "created_at",
]


def _row_to_proveedor(row: dict) -> ProveedorOut:
    return ProveedorOut(
        id=row["id"], nombre=row["nombre"], empresa=row["empresa"] or "", telefono=row["telefono"] or "",
        direccion=row["direccion"] or "", correo=row["correo"] or "", categoria=row["categoria"],
        nit_rut=row["nit_rut"] or "", observacion=row["observacion"] or "",
        activo=row["activo"], created_at=row["created_at"],
    )


@router.get("", response_model=list[ProveedorOut])
def list_proveedores(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                f"SELECT {', '.join(PROVEEDOR_COLUMNS)} FROM proveedores "
                "WHERE usuario_id = :uid AND (nombre ILIKE :q OR empresa ILIKE :q OR telefono ILIKE :q OR correo ILIKE :q) "
                "ORDER BY nombre",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(PROVEEDOR_COLUMNS)} FROM proveedores WHERE usuario_id = :uid ORDER BY nombre",
                uid=current_user.tenant_id,
            )
        return [_row_to_proveedor(dict(zip(PROVEEDOR_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=ProveedorEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE activo), "
            "COUNT(*) FILTER (WHERE categoria = 'A'), "
            "COUNT(*) FILTER (WHERE categoria = 'B'), "
            "COUNT(*) FILTER (WHERE categoria = 'C') "
            "FROM proveedores WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return ProveedorEstadisticasOut(
            total=row[0], activos=row[1], categoria_a=row[2], categoria_b=row[3], categoria_c=row[4]
        )
    finally:
        conn.close()


def _get_proveedor_or_404(conn, usuario_id: int, proveedor_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(PROVEEDOR_COLUMNS)} FROM proveedores WHERE id = :id AND usuario_id = :uid",
        id=proveedor_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proveedor no encontrado")
    return dict(zip(PROVEEDOR_COLUMNS, rows[0]))


@router.get("/{proveedor_id}", response_model=ProveedorOut)
def get_proveedor(proveedor_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_proveedor(_get_proveedor_or_404(conn, current_user.tenant_id, proveedor_id))
    finally:
        conn.close()


@router.post("", response_model=ProveedorOut, status_code=status.HTTP_201_CREATED)
def create_proveedor(payload: ProveedorIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO proveedores "
            "(usuario_id, nombre, empresa, telefono, direccion, correo, categoria, nit_rut, observacion) "
            "VALUES (:uid, :nombre, :empresa, :telefono, :direccion, :correo, :categoria, :nit_rut, :observacion) "
            f"RETURNING {', '.join(PROVEEDOR_COLUMNS)}",
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            empresa=payload.empresa.strip(),
            telefono=payload.telefono.strip(),
            direccion=payload.direccion.strip(),
            correo=payload.correo.strip(),
            categoria=payload.categoria,
            nit_rut=payload.nit_rut.strip(),
            observacion=payload.observacion.strip(),
        )
        return _row_to_proveedor(dict(zip(PROVEEDOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{proveedor_id}", response_model=ProveedorOut)
def update_proveedor(proveedor_id: int, payload: ProveedorIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_proveedor_or_404(conn, current_user.tenant_id, proveedor_id)
        rows = conn.run(
            "UPDATE proveedores SET nombre = :nombre, empresa = :empresa, telefono = :telefono, "
            "direccion = :direccion, correo = :correo, categoria = :categoria, nit_rut = :nit_rut, "
            "observacion = :observacion "
            f"WHERE id = :id AND usuario_id = :uid RETURNING {', '.join(PROVEEDOR_COLUMNS)}",
            id=proveedor_id,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            empresa=payload.empresa.strip(),
            telefono=payload.telefono.strip(),
            direccion=payload.direccion.strip(),
            correo=payload.correo.strip(),
            categoria=payload.categoria,
            nit_rut=payload.nit_rut.strip(),
            observacion=payload.observacion.strip(),
        )
        return _row_to_proveedor(dict(zip(PROVEEDOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{proveedor_id}/activo", response_model=ProveedorOut)
def toggle_activo(proveedor_id: int, payload: ProveedorActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_proveedor_or_404(conn, current_user.tenant_id, proveedor_id)
        rows = conn.run(
            f"UPDATE proveedores SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(PROVEEDOR_COLUMNS)}",
            id=proveedor_id,
            uid=current_user.tenant_id,
            activo=payload.activo,
        )
        return _row_to_proveedor(dict(zip(PROVEEDOR_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{proveedor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proveedor(proveedor_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM proveedores WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=proveedor_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proveedor no encontrado")
    finally:
        conn.close()
