from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import ClienteActivoIn, ClienteEstadisticasOut, ClienteIn, ClienteOut

router = APIRouter(prefix="/clientes", dependencies=[Depends(get_current_user)])

CLIENTE_COLUMNS = [
    "id", "nombre", "telefono", "tipo_doc", "num_doc", "email",
    "direccion", "notas", "activo", "created_at", "updated_at",
]


def _row_to_cliente(row: dict) -> ClienteOut:
    return ClienteOut(**{col: row[col] for col in CLIENTE_COLUMNS})


@router.get("", response_model=list[ClienteOut])
def list_clientes(q: str = Query(default=""), current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        texto = q.strip()
        if texto:
            rows = conn.run(
                f"SELECT {', '.join(CLIENTE_COLUMNS)} FROM clientes "
                "WHERE usuario_id = :uid AND (nombre ILIKE :q OR telefono ILIKE :q OR email ILIKE :q OR num_doc ILIKE :q) "
                "ORDER BY nombre",
                uid=current_user.tenant_id, q=f"%{texto}%",
            )
        else:
            rows = conn.run(
                f"SELECT {', '.join(CLIENTE_COLUMNS)} FROM clientes WHERE usuario_id = :uid ORDER BY nombre",
                uid=current_user.tenant_id,
            )
        return [_row_to_cliente(dict(zip(CLIENTE_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=ClienteEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE activo), "
            "COUNT(*) FILTER (WHERE NOT activo), "
            "COUNT(*) FILTER (WHERE date_trunc('month', created_at) = date_trunc('month', now())) "
            "FROM clientes WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return ClienteEstadisticasOut(total=row[0], activos=row[1], inactivos=row[2], nuevos_mes=row[3])
    finally:
        conn.close()


def _get_cliente_or_404(conn, usuario_id: int, cliente_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(CLIENTE_COLUMNS)} FROM clientes WHERE id = :id AND usuario_id = :uid",
        id=cliente_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    return dict(zip(CLIENTE_COLUMNS, rows[0]))


@router.get("/{cliente_id}", response_model=ClienteOut)
def get_cliente(cliente_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        return _row_to_cliente(_get_cliente_or_404(conn, current_user.tenant_id, cliente_id))
    finally:
        conn.close()


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def create_cliente(payload: ClienteIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run(
            "INSERT INTO clientes (usuario_id, nombre, telefono, tipo_doc, num_doc, email, direccion, notas) "
            "VALUES (:uid, :nombre, :telefono, :tipo_doc, :num_doc, :email, :direccion, :notas) "
            f"RETURNING {', '.join(CLIENTE_COLUMNS)}",
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            telefono=payload.telefono.strip(),
            tipo_doc=payload.tipo_doc.strip(),
            num_doc=payload.num_doc.strip(),
            email=payload.email.strip(),
            direccion=payload.direccion.strip(),
            notas=payload.notas.strip(),
        )
        return _row_to_cliente(dict(zip(CLIENTE_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.put("/{cliente_id}", response_model=ClienteOut)
def update_cliente(cliente_id: int, payload: ClienteIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_cliente_or_404(conn, current_user.tenant_id, cliente_id)
        rows = conn.run(
            "UPDATE clientes SET nombre = :nombre, telefono = :telefono, tipo_doc = :tipo_doc, "
            "num_doc = :num_doc, email = :email, direccion = :direccion, notas = :notas, updated_at = now() "
            f"WHERE id = :id AND usuario_id = :uid RETURNING {', '.join(CLIENTE_COLUMNS)}",
            id=cliente_id,
            uid=current_user.tenant_id,
            nombre=payload.nombre.strip(),
            telefono=payload.telefono.strip(),
            tipo_doc=payload.tipo_doc.strip(),
            num_doc=payload.num_doc.strip(),
            email=payload.email.strip(),
            direccion=payload.direccion.strip(),
            notas=payload.notas.strip(),
        )
        return _row_to_cliente(dict(zip(CLIENTE_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.patch("/{cliente_id}/activo", response_model=ClienteOut)
def toggle_activo(cliente_id: int, payload: ClienteActivoIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        _get_cliente_or_404(conn, current_user.tenant_id, cliente_id)
        rows = conn.run(
            f"UPDATE clientes SET activo = :activo WHERE id = :id AND usuario_id = :uid "
            f"RETURNING {', '.join(CLIENTE_COLUMNS)}",
            id=cliente_id,
            uid=current_user.tenant_id,
            activo=payload.activo,
        )
        return _row_to_cliente(dict(zip(CLIENTE_COLUMNS, rows[0])))
    finally:
        conn.close()


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cliente(cliente_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM clientes WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=cliente_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    finally:
        conn.close()
