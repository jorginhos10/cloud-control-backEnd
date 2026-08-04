import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import UserOut, get_current_user
from app.database import get_connection
from app.schemas import PqrsEstadisticasOut, PqrsIn, PqrsOut, PqrsRespuestaIn, PqrsTokenOut

router = APIRouter(prefix="/pqrs", dependencies=[Depends(get_current_user)])

PQRS_COLUMNS = [
    "id", "nombre", "email", "telefono", "tipo", "calificacion",
    "mensaje", "estado", "respuesta", "leido", "created_at", "updated_at",
]


def _row_to_pqrs(row: dict) -> PqrsOut:
    return PqrsOut(
        id=row["id"], nombre=row["nombre"], email=row["email"] or "", telefono=row["telefono"] or "",
        tipo=row["tipo"], calificacion=row["calificacion"], mensaje=row["mensaje"], estado=row["estado"],
        respuesta=row["respuesta"], leido=row["leido"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _get_pqrs_or_404(conn, usuario_id: int, pqrs_id: int) -> dict:
    rows = conn.run(
        f"SELECT {', '.join(PQRS_COLUMNS)} FROM pqrs WHERE id = :id AND usuario_id = :uid",
        id=pqrs_id, uid=usuario_id,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PQRS no encontrado")
    return dict(zip(PQRS_COLUMNS, rows[0]))


@router.get("", response_model=list[PqrsOut])
def list_pqrs(
    tipo: str = Query(default=""),
    estado: str = Query(default=""),
    q: str = Query(default=""),
    current_user: UserOut = Depends(get_current_user),
):
    conn = get_connection()
    try:
        clauses = ["usuario_id = :uid"]
        params: dict = {"uid": current_user.tenant_id}
        if tipo:
            clauses.append("tipo = :tipo")
            params["tipo"] = tipo
        if estado:
            clauses.append("estado = :estado")
            params["estado"] = estado
        if q.strip():
            clauses.append("(nombre ILIKE :q OR mensaje ILIKE :q)")
            params["q"] = f"%{q.strip()}%"

        rows = conn.run(
            f"SELECT {', '.join(PQRS_COLUMNS)} FROM pqrs WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            **params,
        )
        return [_row_to_pqrs(dict(zip(PQRS_COLUMNS, r))) for r in rows]
    finally:
        conn.close()


@router.get("/estadisticas", response_model=PqrsEstadisticasOut)
def estadisticas(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.run(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE estado = 'pendiente'), "
            "COUNT(*) FILTER (WHERE estado = 'resuelto'), COALESCE(AVG(calificacion), 0) "
            "FROM pqrs WHERE usuario_id = :uid",
            uid=current_user.tenant_id,
        )[0]
        return PqrsEstadisticasOut(
            total=row[0], pendientes=row[1], resueltos=row[2], promedio=round(float(row[3]), 1)
        )
    finally:
        conn.close()


@router.get("/token", response_model=PqrsTokenOut)
def get_token(current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.run("SELECT pqrs_token FROM usuarios WHERE id = :id", id=current_user.tenant_id)
        token = rows[0][0]
        if not token:
            token = secrets.token_hex(16)
            conn.run("UPDATE usuarios SET pqrs_token = :t WHERE id = :id", t=token, id=current_user.tenant_id)
        return PqrsTokenOut(token=token)
    finally:
        conn.close()


@router.patch("/{pqrs_id}/revisar", response_model=PqrsOut)
def revisar(pqrs_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        pqrs = _get_pqrs_or_404(conn, current_user.tenant_id, pqrs_id)
        if pqrs["estado"] != "pendiente":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este PQRS ya fue revisado")
        conn.run(
            "UPDATE pqrs SET estado = 'en_revision', leido = true, updated_at = now() WHERE id = :id",
            id=pqrs_id,
        )
        return _row_to_pqrs(_get_pqrs_or_404(conn, current_user.tenant_id, pqrs_id))
    finally:
        conn.close()


@router.patch("/{pqrs_id}/responder", response_model=PqrsOut)
def responder(pqrs_id: int, payload: PqrsRespuestaIn, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        pqrs = _get_pqrs_or_404(conn, current_user.tenant_id, pqrs_id)
        if pqrs["estado"] == "resuelto":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este PQRS ya fue resuelto")
        conn.run(
            "UPDATE pqrs SET respuesta = :r, estado = 'resuelto', leido = true, updated_at = now() WHERE id = :id",
            r=payload.respuesta.strip(), id=pqrs_id,
        )
        return _row_to_pqrs(_get_pqrs_or_404(conn, current_user.tenant_id, pqrs_id))
    finally:
        conn.close()


@router.delete("/{pqrs_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(pqrs_id: int, current_user: UserOut = Depends(get_current_user)):
    conn = get_connection()
    try:
        deleted = conn.run(
            "DELETE FROM pqrs WHERE id = :id AND usuario_id = :uid RETURNING id",
            id=pqrs_id, uid=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PQRS no encontrado")
    finally:
        conn.close()
