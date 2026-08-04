import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.clientes import router as clientes_router
from app.cupones import router as cupones_router
from app.dashboard import router as dashboard_router
from app.database import get_connection
from app.domicilio_publico import router as domicilio_publico_router
from app.domicilios import router as domicilios_router
from app.ingresos import router as ingresos_router
from app.insumos import router as insumos_router
from app.mesas import router as mesas_router
from app.marketplace import router as marketplace_router
from app.menu_digital import router as menu_digital_router
from app.menu_publico import router as menu_publico_router
from app.pqrs import router as pqrs_router
from app.pqrs_publico import router as pqrs_publico_router
from app.perdidas import router as perdidas_router
from app.proveedores import router as proveedores_router
from app.recetas import router as recetas_router
from app.reportes import router as reportes_router
from app.usuarios import router as usuarios_router
from app.ventas import router as ventas_router

app = FastAPI(title="ChefControl API")

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(mesas_router)
app.include_router(cupones_router)
app.include_router(ventas_router)
app.include_router(clientes_router)
app.include_router(insumos_router)
app.include_router(recetas_router)
app.include_router(ingresos_router)
app.include_router(menu_digital_router)
app.include_router(menu_publico_router)
app.include_router(pqrs_router)
app.include_router(pqrs_publico_router)
app.include_router(domicilios_router)
app.include_router(domicilio_publico_router)
app.include_router(reportes_router)
app.include_router(marketplace_router)
app.include_router(proveedores_router)
app.include_router(perdidas_router)
app.include_router(usuarios_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/db-check")
def db_check():
    conn = get_connection()
    try:
        conn.run("SELECT 1")
        return {"database": "ok"}
    finally:
        conn.close()
