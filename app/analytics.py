"""Registro liviano de visitas al front-client, para que el SuperAdmin pueda ver cuánta gente
única (por IP) llega a la plataforma. Público (sin login: hasta el login mismo debe contar)."""
from fastapi import APIRouter, Request, status

from app.database import get_connection
from app.geo import _client_ip
from app.lugares import limitar
from app.schemas import VisitaIn

router = APIRouter(prefix="/analytics")


@router.post("/visita", status_code=status.HTTP_204_NO_CONTENT)
def registrar_visita(request: Request, payload: VisitaIn):
    limitar(request, "visita", 20)
    ip = _client_ip(request) or "desconocida"
    conn = get_connection()
    try:
        conn.run(
            "INSERT INTO visitas_ip (ip, ruta) VALUES (:ip, :ruta)",
            ip=ip, ruta=payload.ruta.strip()[:200],
        )
    finally:
        conn.close()
