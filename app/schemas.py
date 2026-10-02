from datetime import date, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, EmailStr, Field


EstadoAprobacion = Literal["pendiente_datos", "pendiente_aprobacion", "aprobado", "rechazado"]


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=150, alias="fullName")
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)

    model_config = {"populate_by_name": True}


class LoginIn(BaseModel):
    email: str = Field(min_length=1)
    password: str


class ImpersonateIn(BaseModel):
    user_id: int


class UserOut(BaseModel):
    id: int
    username: str
    nombre: str
    email: str
    rol: str
    activo: bool
    propietario: bool
    ultimo_login: Optional[datetime] = Field(default=None, serialization_alias="ultimoLogin")
    propietario_id: Optional[int] = Field(default=None, serialization_alias="propietarioId")
    tenant_id: int = Field(serialization_alias="tenantId")
    fecha_creacion: datetime = Field(serialization_alias="fechaCreacion")
    estado_aprobacion: EstadoAprobacion = Field(default="aprobado", serialization_alias="estadoAprobacion")
    motivo_rechazo: str = Field(default="", serialization_alias="motivoRechazo")

    model_config = {"populate_by_name": True}


class PerfilUpdateIn(BaseModel):
    nombre: str = Field(min_length=3, max_length=150)
    email: EmailStr


class CambiarPasswordIn(BaseModel):
    actual: str
    nueva: str = Field(min_length=6, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


Estado = Literal["disponible", "ocupada", "reservada", "mantenimiento"]


class ZonaIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class ZonaOut(BaseModel):
    id: int
    key: str
    label: str


class MesaIn(BaseModel):
    numero: int = Field(ge=1)
    nombre: str = Field(default="", max_length=100)
    capacidad: int = Field(ge=1, default=4)
    zona: str
    estado: Estado = "disponible"
    activo: bool = True


class MesaEstadoIn(BaseModel):
    estado: Estado


class MesaActivoIn(BaseModel):
    activo: bool


class MesaOut(BaseModel):
    id: int
    numero: int
    nombre: str
    capacidad: int
    zona: str
    estado: Estado
    activo: bool


TipoCupon = Literal["porcentaje", "valor", "producto"]
EstadoCupon = Literal["activo", "inactivo", "usado"]


class CuponIn(BaseModel):
    nombre: str = Field(default="", max_length=100)
    tipo: TipoCupon = "porcentaje"
    descuento: float = Field(gt=0)
    usos_max: int = Field(ge=1, default=1)
    expira_en: Optional[str] = None
    id_receta: Optional[int] = None
    codigo: str = Field(default="", max_length=8)


class CuponOut(BaseModel):
    id: int
    codigo: str
    nombre: str
    tipo: TipoCupon
    descuento: float
    usos_max: int
    usos_actual: int
    estado: EstadoCupon
    expira_en: Optional[str] = None
    id_receta: Optional[int] = None
    receta_nombre: Optional[str] = None
    created_at: datetime


class CuponEstadisticasOut(BaseModel):
    total: int
    activos: int
    usados: int
    inactivos: int


class CuponMesOut(BaseModel):
    mes: int
    usos: int
    total: float


class CodigoDisponibleOut(BaseModel):
    disponible: Optional[bool]


EstadoVenta = Literal["abierta", "en_preparacion", "lista", "entregada", "cerrada", "cancelada"]
TipoVenta = Literal["mesa", "directa", "domicilio"]
MetodoPago = Literal["efectivo", "tarjeta", "transferencia", "mixto"]


class VentaCrearIn(BaseModel):
    mesa_id: Optional[int] = None


class MesaCambioIn(BaseModel):
    destino_id: int


class VentaItemIn(BaseModel):
    receta_id: int
    cantidad: int = Field(ge=1, default=1)


class VentaItemCantidadIn(BaseModel):
    cantidad: int = Field(ge=1)


class VentaItemOut(BaseModel):
    id: int
    receta_id: Optional[int] = None
    nombre: str
    cantidad: int
    precio_unitario: float
    subtotal: float


class VentaOut(BaseModel):
    id: int
    mesa_id: Optional[int] = None
    tipo: TipoVenta
    estado: EstadoVenta
    total: float
    descuento: float = 0
    cupon_codigo: Optional[str] = None
    notas: str
    metodo_pago: Optional[MetodoPago] = None
    pago_efectivo: float = 0
    pago_tarjeta: float = 0
    pago_transferencia: float = 0
    propina: float = 0
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime] = None
    cliente_id: Optional[int] = None
    cliente_nombre: Optional[str] = None
    items: list[VentaItemOut] = []


class VentaEstadoIn(BaseModel):
    estado: EstadoVenta


class VentaClienteIn(BaseModel):
    cliente_id: Optional[int] = None


class VentaNotasIn(BaseModel):
    notas: str = Field(default="", max_length=500)


class VentaCuponIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=8)


class VentaCobrarIn(BaseModel):
    metodo_pago: MetodoPago = "efectivo"
    pago_efectivo: float = Field(ge=0, default=0)
    pago_tarjeta: float = Field(ge=0, default=0)
    pago_transferencia: float = Field(ge=0, default=0)
    propina: float = Field(ge=0, default=0)


class VentaListadoItemOut(BaseModel):
    id: int
    fecha: datetime
    tipo: TipoVenta
    estado: EstadoVenta
    mesa_numero: Optional[int] = None
    platos: int
    total: float
    metodo_pago: Optional[MetodoPago] = None


class PropinaItemOut(BaseModel):
    id: int
    fecha: Optional[datetime] = None
    tipo: TipoVenta
    mesa_numero: Optional[int] = None
    propina: float
    total: float
    metodo_pago: Optional[MetodoPago] = None


class VentaListadoOut(BaseModel):
    items: list[VentaListadoItemOut] = []
    total: int
    monto_total: float
    pagina: int
    total_paginas: int


class CatalogoItemOut(BaseModel):
    id: int
    nombre: str
    categoria: str
    precio_venta: float
    disponible: Optional[int] = None
    imagen_url: Optional[str] = None


class NegocioPublicoOut(BaseModel):
    nombre: str = ""
    logo_url: Optional[str] = None
    eslogan: str = ""
    apariencia: str = "violet-original"


class CocinaItemOut(BaseModel):
    id: int
    nombre: str
    cantidad: int
    categoria: str


class CocinaOrdenOut(BaseModel):
    id: int
    tipo: str
    estado: EstadoVenta
    notas: str
    fecha_apertura: datetime
    mesa_numero: Optional[int] = None
    mesa_nombre: Optional[str] = None
    mesa_zona: Optional[str] = None
    items: list[CocinaItemOut] = []
    origen: Literal["venta", "domicilio"] = "venta"
    cliente_nombre: Optional[str] = None
    direccion: Optional[str] = None


class SalonMesaOut(BaseModel):
    id: int
    numero: int
    nombre: str
    capacidad: int
    zona: str
    estado: Estado
    activo: bool
    venta_id: Optional[int] = None
    orden_estado: Optional[str] = None
    orden_total: float = 0
    items_count: int = 0
    orden_inicio: Optional[datetime] = None


class SalonEstadisticasOut(BaseModel):
    total: int
    disponibles: int
    ocupadas: int
    reservadas: int
    ingresos_en_curso: float


class VentaDirectaEstadisticasOut(BaseModel):
    ventas_hoy: int
    ingresos_hoy: float


class ClienteIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    telefono: str = Field(default="", max_length=30)
    tipo_doc: str = Field(default="", max_length=20)
    num_doc: str = Field(default="", max_length=60)
    email: str = Field(default="", max_length=100)
    direccion: str = Field(default="")
    notas: str = Field(default="")


class ClienteActivoIn(BaseModel):
    activo: bool


class ClienteOut(BaseModel):
    id: int
    nombre: str
    telefono: str
    tipo_doc: str
    num_doc: str
    email: str
    direccion: str
    notas: str
    activo: bool
    created_at: datetime
    updated_at: datetime


class ClienteEstadisticasOut(BaseModel):
    total: int
    activos: int
    inactivos: int
    nuevos_mes: int


StockEstado = Literal["critico", "bajo", "ok"]


class InsumoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(default="")
    categoria: str = Field(default="otros", max_length=60)
    unidad_medida: str = Field(default="unidad", max_length=30)
    cantidad_stock: float = Field(ge=0, default=0)
    cantidad_minima: float = Field(ge=0, default=0)
    precio_unitario: float = Field(ge=0, default=0)
    activo: bool = True


class InsumoActivoIn(BaseModel):
    activo: bool


class InsumoOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    categoria: str
    unidad_medida: str
    cantidad_stock: float
    cantidad_minima: float
    precio_unitario: float
    activo: bool
    created_at: datetime
    stock_estado: StockEstado


class InsumoEstadisticasOut(BaseModel):
    total: int
    activos: int
    stock_bajo: int
    categorias: int


EstadoActivoFijo = Literal["bueno", "regular", "danado", "perdido", "de_baja"]


class ActivoFijoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(default="")
    categoria: str = Field(default="otros", max_length=60)
    cantidad: int = Field(ge=1, default=1)
    ubicacion: str = Field(default="", max_length=100)
    estado: EstadoActivoFijo = "bueno"
    valor_unitario: float = Field(ge=0, default=0)
    activo: bool = True


class ActivoFijoActivoIn(BaseModel):
    activo: bool


class ActivoFijoEstadoIn(BaseModel):
    estado: EstadoActivoFijo
    cantidad: Optional[int] = Field(ge=1, default=None)
    nota: str = Field(default="", max_length=500)


class ActivoFijoOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    categoria: str
    cantidad: int
    ubicacion: str
    estado: EstadoActivoFijo
    valor_unitario: float
    activo: bool
    created_at: datetime


class ActivoFijoEstadisticasOut(BaseModel):
    total: int
    activos: int
    danados: int
    categorias: int


class ActivoFijoHistorialOut(BaseModel):
    id: int
    estado_anterior: EstadoActivoFijo
    estado_nuevo: EstadoActivoFijo
    cantidad_anterior: int
    cantidad_nueva: int
    nota: str
    registrado_por: str
    created_at: datetime


class CategoriaRecetaIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class CategoriaRecetaOut(BaseModel):
    id: int
    key: str
    label: str


class RecetaIngredienteIn(BaseModel):
    id_insumo: int
    cantidad: float = Field(gt=0)


class RecetaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str = Field(default="")
    categoria: str = Field(default="plato_fuerte", max_length=60)
    tiempo_preparacion: int = Field(ge=0, default=0)
    porciones: int = Field(ge=1, default=1)
    precio_venta: float = Field(ge=0, default=0)
    activo: bool = True
    imagen_url: Optional[str] = None
    ingredientes: list[RecetaIngredienteIn] = []


class RecetaActivoIn(BaseModel):
    activo: bool


class RecetaIngredienteOut(BaseModel):
    id_insumo: int
    insumo_nombre: str
    unidad_medida: str
    cantidad: float
    costo: float


class RecetaOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    categoria: str
    tiempo_preparacion: int
    porciones: int
    precio_venta: float
    activo: bool
    created_at: datetime
    imagen_url: Optional[str] = None
    ingredientes: list[RecetaIngredienteOut] = []
    costo_total: float
    margen: float


class RecetaEstadisticasOut(BaseModel):
    total: int
    activas: int
    categorias: int
    ingredientes_configurados: int


EstadoIngreso = Literal["aceptado", "anulado"]


class IngresoItemIn(BaseModel):
    insumo_id: Optional[int] = None
    articulo: str = Field(min_length=1, max_length=150)
    cantidad: float = Field(gt=0)
    precio_unitario: float = Field(ge=0, default=0)


class IngresoIn(BaseModel):
    concepto: str = Field(default="", max_length=500)
    impuesto_porcentaje: float = Field(ge=0, le=100, default=0)
    items: list[IngresoItemIn] = []


class IngresoItemOut(BaseModel):
    id: int
    insumo_id: Optional[int] = None
    articulo: str
    cantidad: float
    precio_unitario: float
    subtotal: float


class IngresoOut(BaseModel):
    id: int
    radicado: str
    fecha: date
    concepto: str
    impuesto_porcentaje: float
    subtotal: float
    impuesto: float
    total: float
    estado: EstadoIngreso
    created_at: datetime
    items: list[IngresoItemOut] = []


class IngresoEstadisticasOut(BaseModel):
    ingresos_periodo: int
    total_ingresado: float
    anulados: int


class MenuDigitalIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str = Field(default="", max_length=1000)
    activo: bool = True


class MenuDigitalConfigIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    mesa_id: Optional[int] = None


class MenuItemsIn(BaseModel):
    receta_ids: list[int] = []


class MenuDigitalOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    activo: bool
    token: str
    mesa_id: Optional[int] = None
    mesa_numero: Optional[int] = None
    mesa_nombre: Optional[str] = None
    created_at: datetime
    items_count: int = 0


class MenuItemOut(BaseModel):
    receta_id: int
    nombre: str
    descripcion: str
    categoria: str
    precio_venta: float
    disponible: Optional[int] = None
    orden: int
    imagen_url: Optional[str] = None


class MenuDigitalDetalleOut(MenuDigitalOut):
    items: list[MenuItemOut] = []


class MenuPublicoDetalleOut(MenuDigitalDetalleOut):
    negocio_nombre: str = ""
    negocio_logo_url: Optional[str] = None
    negocio_eslogan: str = ""
    negocio_apariencia: str = "violet-original"


class MenuPedidoItemIn(BaseModel):
    receta_id: int
    cantidad: int = Field(ge=1, default=1)


class MenuPedidoIn(BaseModel):
    items: list[MenuPedidoItemIn] = []


class MenuPedidoOut(BaseModel):
    venta_id: int
    estado: EstadoVenta
    total: float


class OrdenPublicaOut(BaseModel):
    id: int
    estado: EstadoVenta
    total: float
    items: list[VentaItemOut] = []


TipoPqrs = Literal["peticion", "queja", "reclamo", "sugerencia"]
EstadoPqrs = Literal["pendiente", "en_revision", "resuelto"]


class PqrsIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    email: str = Field(default="", max_length=100)
    telefono: str = Field(default="", max_length=30)
    tipo: TipoPqrs = "sugerencia"
    calificacion: int = Field(ge=1, le=5, default=5)
    mensaje: str = Field(min_length=1, max_length=1000)


class PqrsRespuestaIn(BaseModel):
    respuesta: str = Field(min_length=1, max_length=2000)


class PqrsOut(BaseModel):
    id: int
    nombre: str
    email: str
    telefono: str
    tipo: TipoPqrs
    calificacion: int
    mensaje: str
    estado: EstadoPqrs
    respuesta: Optional[str] = None
    leido: bool
    created_at: datetime
    updated_at: datetime


class PqrsEstadisticasOut(BaseModel):
    total: int
    pendientes: int
    resueltos: int
    promedio: float


class PqrsTokenOut(BaseModel):
    token: str


class PqrsValidoOut(BaseModel):
    valido: bool


TipoDomicilio = Literal["domicilio", "recoger"]
MetodoPagoDomicilio = Literal["efectivo", "tarjeta", "transferencia"]
EstadoDomicilio = Literal["pendiente", "preparacion", "listo", "en_camino", "entregado", "cancelado"]


class DomicilioItemIn(BaseModel):
    receta_id: int
    cantidad: int = Field(ge=1, default=1)


class DomicilioPedidoIn(BaseModel):
    nombre_cliente: str = Field(min_length=1, max_length=100)
    telefono: str = Field(default="", max_length=30)
    direccion: str = Field(default="", max_length=500)
    barrio: str = Field(default="", max_length=100)
    notas: str = Field(default="", max_length=500)
    tipo: TipoDomicilio = "domicilio"
    metodo_pago: MetodoPagoDomicilio = "efectivo"
    items: list[DomicilioItemIn] = []
    # Ubicación del cliente (GPS del celular) para calcular el domicilio automático.
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class DomicilioInternoIn(DomicilioPedidoIn):
    valor_domicilio: Optional[float] = Field(default=None, ge=0)


ModoDomicilio = Literal["gratis", "personalizado", "automatico"]


class DomicilioConfigIn(BaseModel):
    modo: ModoDomicilio = "personalizado"
    valor_fijo: Optional[float] = Field(default=None, ge=0)
    tarifa_base: float = Field(default=0, ge=0)
    km_base: float = Field(default=2, ge=0)
    valor_km: float = Field(default=0, ge=0)
    radio_max_km: Optional[float] = Field(default=None, gt=0)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class DomicilioUbicacionOut(BaseModel):
    lat: float
    lng: float


class DomicilioCotizacionIn(BaseModel):
    direccion: str = Field(default="", max_length=500)
    barrio: str = Field(default="", max_length=100)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class LugarSugerenciaOut(BaseModel):
    id: str
    principal: str
    secundario: str = ""
    distancia_km: Optional[float] = None
    # Quién aportó la sugerencia: define la atribución que debe mostrarse.
    fuente: str = "google"


class LugarDetalleOut(BaseModel):
    direccion: str = ""
    barrio: str = ""
    lat: float
    lng: float


class DomicilioCotizacionOut(BaseModel):
    modo: ModoDomicilio
    valor: Optional[float] = None
    distancia_km: Optional[float] = None
    fuera_de_cobertura: bool = False
    mensaje: str = ""


class DomicilioEstadoIn(BaseModel):
    estado: EstadoDomicilio
    valor_domicilio: Optional[float] = Field(default=None, ge=0)
    # Obligatorio cuando el negocio cancela un pedido que ya había aceptado (preparación o listo).
    motivo: Optional[str] = Field(default=None, max_length=500)


class DomicilioItemOut(BaseModel):
    id: int
    receta_id: Optional[int] = None
    nombre: str
    precio: float
    cantidad: int


class DomicilioOut(BaseModel):
    id: int
    token_pedido: str
    nombre_cliente: str
    telefono: str
    direccion: str
    barrio: str
    notas: str
    tipo: TipoDomicilio
    metodo_pago: str = ""
    estado: EstadoDomicilio
    total: float
    valor_domicilio: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    motivo_cancelacion: str = ""
    items: list[DomicilioItemOut] = []


class DomicilioEstadisticasOut(BaseModel):
    activos: int
    pendientes: int


class DomicilioTokenOut(BaseModel):
    token: str


class DomicilioChatMensajeIn(BaseModel):
    mensaje: str = Field(min_length=1, max_length=1000)


class DomicilioChatMensajeOut(BaseModel):
    id: int
    de: Literal["cliente", "admin"]
    mensaje: str
    leido: bool
    created_at: datetime


class DomicilioChatResumenOut(BaseModel):
    domicilio_id: int
    nombre_cliente: str
    tipo: TipoDomicilio
    estado: EstadoDomicilio
    ultimo_mensaje: Optional[str] = None
    ultimo_mensaje_de: Optional[Literal["cliente", "admin"]] = None
    ultimo_mensaje_at: Optional[datetime] = None
    no_leidos: int


class ReporteXGeneralOut(BaseModel):
    total_ventas: int
    total_monto: float
    ticket_promedio: float
    total_platos: int


class ReporteXProductoOut(BaseModel):
    receta_id: Optional[int] = None
    nombre: str
    categoria: str
    cantidad: int
    monto: float


class ReporteXHoraOut(BaseModel):
    hora: int
    ventas: int
    monto: float


class ReporteXOut(BaseModel):
    fecha: date
    general: ReporteXGeneralOut
    por_producto: list[ReporteXProductoOut] = []
    por_hora: list[ReporteXHoraOut] = []


class CierreZPreviewOut(BaseModel):
    fecha_desde: datetime
    fecha_hasta: datetime
    total_ventas: int
    total_monto: float
    por_producto: list[ReporteXProductoOut] = []


class CierreZOut(BaseModel):
    id: int
    numero_z: int
    fecha_desde: datetime
    fecha_hasta: datetime
    total_ventas: int
    total_monto: float
    por_producto: list[ReporteXProductoOut] = []
    created_at: datetime


class CierreZResumenOut(BaseModel):
    id: int
    numero_z: int
    fecha_desde: datetime
    fecha_hasta: datetime
    total_ventas: int
    total_monto: float
    created_at: datetime


class CierreZMesOut(BaseModel):
    mes: int
    total_monto: float
    total_ventas: int


EstadoListaCompra = Literal["pendiente", "recibido", "cancelado"]


class ListaCompraItemIn(BaseModel):
    insumo_id: int
    cantidad: float = Field(gt=0)


class ListaCompraIn(BaseModel):
    notas: str = Field(default="", max_length=500)
    items: list[ListaCompraItemIn] = []


class ListaCompraItemOut(BaseModel):
    id: int
    insumo_id: Optional[int] = None
    nombre: str
    cantidad: float
    precio_unitario: float
    subtotal: float


class ListaCompraOut(BaseModel):
    id: int
    numero: str
    estado: EstadoListaCompra
    notas: str
    total: float
    ingreso_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    items: list[ListaCompraItemOut] = []


class ListaCompraEstadisticasOut(BaseModel):
    pendientes: int
    recibidas: int


class MarketplaceItemOut(BaseModel):
    id: int
    nombre: str
    categoria: str
    unidad_medida: str
    precio_unitario: float
    precio_envio: float = 0
    imagenes: list[str] = []
    descripcion: Optional[str] = None


class TiendaOut(BaseModel):
    id: str
    nombre: str
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    color: str = "#16a085"
    total_productos: int


class PlanPublicoOut(BaseModel):
    id: int
    nombre: str
    slug: str
    descripcion: Optional[str] = None
    precio: float
    periodo: str
    color: str
    caracteristicas: list[str]
    destacado: bool
    actual: bool = False


class SeleccionarPlanIn(BaseModel):
    plan_id: int


class PedidoItemIn(BaseModel):
    producto_id: int
    cantidad: float = Field(gt=0)


class PedidoIn(BaseModel):
    tienda_id: int
    items: list[PedidoItemIn]
    cupon_codigo: Optional[str] = None


class PedidoItemOut(BaseModel):
    id: int
    producto_id: int
    nombre: str
    categoria: str
    precio_unitario: float
    cantidad: float
    subtotal: float


class PedidoOut(BaseModel):
    id: int
    radicado: str = ""
    tienda_id: int
    tienda_nombre: str
    subtotal: float
    descuento: float
    envio: float = 0
    total: float
    cupon_codigo: Optional[str] = None
    estado: str
    wompi_reference: str
    wompi_transaction_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: list[PedidoItemOut] = []


class WompiCheckoutOut(BaseModel):
    checkout_url: str
    public_key: str
    currency: str = "COP"
    amount_in_cents: int
    reference: str
    signature: str
    redirect_url: str


class PedidoConCheckoutOut(BaseModel):
    pedido: PedidoOut
    wompi: WompiCheckoutOut


class ConfirmarTransaccionIn(BaseModel):
    transaction_id: str


class SuscripcionPagoOut(BaseModel):
    estado: str
    plan: PlanPublicoOut
    wompi: Optional[WompiCheckoutOut] = None


class CuponValidarIn(BaseModel):
    codigo: str
    subtotal: float


class CuponValidarOut(BaseModel):
    valido: bool
    mensaje: str = ""
    tipo: Optional[str] = None
    valor: Optional[float] = None
    descuento: float = 0


CategoriaProveedor = Literal["A", "B", "C"]


class ProveedorIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    empresa: str = Field(default="", max_length=150)
    telefono: str = Field(default="", max_length=30)
    direccion: str = Field(default="", max_length=255)
    correo: str = Field(default="", max_length=100)
    categoria: CategoriaProveedor = "B"
    nit_rut: str = Field(default="", max_length=30)
    observacion: str = Field(default="")


class ProveedorActivoIn(BaseModel):
    activo: bool


class ProveedorOut(BaseModel):
    id: int
    nombre: str
    empresa: str
    telefono: str
    direccion: str
    correo: str
    categoria: CategoriaProveedor
    nit_rut: str
    observacion: str
    activo: bool
    created_at: datetime


class ProveedorEstadisticasOut(BaseModel):
    total: int
    activos: int
    categoria_a: int
    categoria_b: int
    categoria_c: int


MotivoPerdida = Literal["vencido", "danado", "extraviado", "error_cocina", "otro"]
EstadoPerdida = Literal["aceptado", "anulado"]


class PerdidaIn(BaseModel):
    insumo_id: int
    cantidad: float = Field(gt=0)
    motivo: MotivoPerdida = "otro"
    descripcion: str = Field(default="", max_length=500)


class PerdidaOut(BaseModel):
    id: int
    insumo_id: int
    insumo_nombre: str
    unidad_medida: str
    cantidad: float
    motivo: MotivoPerdida
    descripcion: str
    costo_unitario: float
    valor_perdida: float
    stock_anterior: float
    stock_nuevo: float
    estado: EstadoPerdida
    created_at: datetime


class DashboardTotalesOut(BaseModel):
    ventas: float
    costos: float
    propinas: float
    ganancias: float


class DashboardProductoMontoOut(BaseModel):
    producto: str
    monto: float


class DashboardProductoCantidadOut(BaseModel):
    producto: str
    cantidad: int


class DashboardCategoriaOut(BaseModel):
    categoria: str
    monto: float


class DashboardResumenOut(BaseModel):
    totales: DashboardTotalesOut
    ventas_por_mes: list[float] = []
    top_productos: list[DashboardProductoMontoOut] = []
    productos_mas_solicitados: list[DashboardProductoCantidadOut] = []
    ventas_por_categoria: list[DashboardCategoriaOut] = []


class PerdidaEstadisticasOut(BaseModel):
    total_salidas: int
    unidades_perdidas: float
    valor_perdida_total: float
    top_insumo_nombre: Optional[str] = None
    top_insumo_cantidad: Optional[float] = None


RolStaff = Literal["admin", "cocina", "inventario", "mesero"]


class UsuarioStaffIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    apellido: str = Field(min_length=1, max_length=150)
    telefono: str = Field(min_length=1, max_length=30)
    email: EmailStr
    numero_documento: str = Field(min_length=1, max_length=30)
    rol: RolStaff = "mesero"
    activo: bool = True


class UsuarioStaffUpdateIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    apellido: str = Field(min_length=1, max_length=150)
    telefono: str = Field(min_length=1, max_length=30)
    numero_documento: str = Field(min_length=1, max_length=30)
    rol: RolStaff
    activo: bool


class UsuarioActivoIn(BaseModel):
    activo: bool


class UsuarioResetPasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=72)


class UsuarioStaffOut(BaseModel):
    id: int
    username: str
    nombre: str
    apellido: str
    telefono: str
    email: str
    numero_documento: str
    rol: RolStaff
    activo: bool
    propietario: bool
    ultimo_login: Optional[datetime] = None


TamanoPapel = Literal["58mm", "80mm", "carta"]
ModoImpresionComanda = Literal["si", "no", "driver"]


class ConfiguracionImpresionOut(BaseModel):
    modo_impresion_comanda: ModoImpresionComanda = Field(serialization_alias="modoImpresionComanda")
    tamano_papel_comanda: TamanoPapel = Field(serialization_alias="tamanoPapelComanda")

    model_config = {"populate_by_name": True}


class ConfiguracionImpresionIn(BaseModel):
    modo_impresion_comanda: ModoImpresionComanda = Field(alias="modoImpresionComanda")
    tamano_papel_comanda: TamanoPapel = Field(alias="tamanoPapelComanda")

    model_config = {"populate_by_name": True}


class NegocioIn(BaseModel):
    nombre: str = Field(default="", max_length=150)
    tipo: str = Field(default="Restaurante", max_length=50)
    moneda: str = Field(default="USD", max_length=3)
    eslogan: str = Field(default="", max_length=200)
    horario_apertura: str = Field(default="08:00", max_length=5)
    horario_cierre: str = Field(default="22:00", max_length=5)
    rut: str = Field(default="", max_length=50)
    direccion: str = Field(default="", max_length=200)
    ciudad: str = Field(default="", max_length=100)
    telefono: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=150)
    sitio_web: str = Field(default="", max_length=200)
    logo_url: Optional[str] = None


class NegocioOut(NegocioIn):
    updated_at: datetime


class NegocioAparienciaIn(BaseModel):
    apariencia: str = Field(min_length=1, max_length=30)


class NegocioAparienciaOut(BaseModel):
    apariencia: str
    automatico_default: str = Field(default="violet-original", serialization_alias="automaticoDefault")

    model_config = {"populate_by_name": True}


AmbienteDian = Literal["habilitacion", "produccion"]
TipoDocumentoElectronico = Literal["factura_electronica", "documento_equivalente_pos"]
TipoPersona = Literal["juridica", "natural"]
RegimenIva = Literal["responsable_iva", "no_responsable_iva"]
ResponsabilidadFiscal = Literal["O-13", "O-15", "O-23", "O-47", "R-99-PN"]


class FacturacionElectronicaBase(BaseModel):
    activa: bool = False
    ambiente: AmbienteDian = "habilitacion"
    tipo_documento: TipoDocumentoElectronico = "factura_electronica"

    tipo_persona: TipoPersona = "juridica"
    nit: str = Field(default="", pattern=r"^(\d{6,10})?$")
    razon_social: str = Field(default="", max_length=200)
    nombre_comercial: str = Field(default="", max_length=200)
    regimen_iva: RegimenIva = "responsable_iva"
    responsabilidades_fiscales: list[ResponsabilidadFiscal] = Field(default_factory=list, max_length=5)
    actividad_economica: str = Field(default="", pattern=r"^(\d{4})?$")
    matricula_mercantil: str = Field(default="", max_length=30)
    direccion: str = Field(default="", max_length=200)
    departamento: str = Field(default="", max_length=100)
    ciudad: str = Field(default="", max_length=100)
    codigo_municipio: str = Field(default="", pattern=r"^(\d{5})?$")
    codigo_postal: str = Field(default="", pattern=r"^(\d{6})?$")
    telefono: str = Field(default="", max_length=30)
    email_facturacion: Union[EmailStr, Literal[""]] = ""

    resolucion_numero: str = Field(default="", max_length=30)
    resolucion_fecha: Optional[date] = None
    prefijo: str = Field(default="", pattern=r"^[A-Za-z0-9]{0,10}$")
    rango_desde: Optional[int] = Field(default=None, ge=1)
    rango_hasta: Optional[int] = Field(default=None, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None

    proveedor_tecnologico: str = Field(default="", max_length=100)
    usuario_api: str = Field(default="", max_length=150)
    software_id: str = Field(default="", max_length=60)
    test_set_id: str = Field(default="", max_length=60)
    enviar_email_cliente: bool = True


class FacturacionElectronicaIn(FacturacionElectronicaBase):
    # Write-only: empty/absent keeps the stored value, non-empty replaces it.
    clave_tecnica: str = Field(default="", max_length=100)
    token_api: str = Field(default="", max_length=500)
    software_pin: str = Field(default="", max_length=60)


class FacturacionElectronicaOut(FacturacionElectronicaBase):
    dv: str = ""
    clave_tecnica_configurada: bool = False
    token_api_configurado: bool = False
    software_pin_configurado: bool = False
    updated_at: Optional[datetime] = None


TipoDocumentoComercio = Literal["identificacion_fiscal", "documento_representante", "camara_comercio", "otro"]


class OnboardingDatosIn(BaseModel):
    model_config = {"str_strip_whitespace": True}

    numero_documento: str = Field(min_length=5, max_length=20, pattern=r"^[0-9A-Za-z.\-]+$")
    telefono: str = Field(min_length=7, max_length=30)
    nombre_negocio: str = Field(min_length=2, max_length=150)
    tipo_negocio: Literal["Store", "Restobar"]
    rut: str = Field(min_length=5, max_length=50)
    direccion: str = Field(min_length=3, max_length=200)
    ciudad: str = Field(min_length=2, max_length=100)
    sitio_web: str = Field(default="", max_length=200)


class OnboardingLogoIn(BaseModel):
    logo_url: Optional[str] = Field(default=None, max_length=3_000_000)


class OnboardingPlanIn(BaseModel):
    plan_id: int


class OnboardingDocumentoIn(BaseModel):
    tipo: TipoDocumentoComercio
    nombre_archivo: str = Field(min_length=1, max_length=200)
    contenido_base64: str = Field(min_length=1, max_length=7_500_000)


class OnboardingDocumentoOut(BaseModel):
    id: int
    tipo: TipoDocumentoComercio
    nombre_archivo: str
    content_type: str
    tamano: int
    created_at: datetime
    estado: Literal["pendiente", "rechazado"] = "pendiente"
    motivo_rechazo: str = ""


class OnboardingOut(BaseModel):
    numero_documento: str = ""
    telefono: str = ""
    nombre_negocio: str = ""
    tipo_negocio: str = "Restaurante"
    rut: str = ""
    direccion: str = ""
    ciudad: str = ""
    sitio_web: str = ""
    logo_url: Optional[str] = None
    plan_solicitado_id: Optional[int] = None
    documentos: list[OnboardingDocumentoOut] = []
    estado_aprobacion: EstadoAprobacion = "pendiente_datos"
    motivo_rechazo: str = ""
    tipos_comercio_habilitados: list[str] = ["Store", "Restobar"]


TipoContrato = Literal["indefinido", "fijo", "obra_labor", "prestacion_servicios"]
TipoPagoNomina = Literal["mensual", "quincenal", "por_horas", "por_dia"]
TipoCuentaBancaria = Literal["ahorros", "corriente"]
TipoPeriodoNomina = Literal["quincenal", "mensual", "diario"]
EstadoPeriodoNomina = Literal["borrador", "calculada", "pagada"]
DiaSemana = Literal["lun", "mar", "mie", "jue", "vie", "sab", "dom"]


class HorarioDia(BaseModel):
    activo: bool = False
    horas: float = Field(ge=0, le=24, default=0)


class NominaEmpleadoIn(BaseModel):
    tipo_contrato: TipoContrato = "indefinido"
    tipo_pago: TipoPagoNomina = "mensual"
    salario_base: float = Field(ge=0, default=0)
    valor_hora: float = Field(ge=0, default=0)
    valor_dia: float = Field(ge=0, default=0)
    eps: str = Field(default="", max_length=100)
    afp: str = Field(default="", max_length=100)
    arl: str = Field(default="", max_length=100)
    fecha_ingreso: Optional[date] = None
    banco: str = Field(default="", max_length=100)
    tipo_cuenta: Optional[TipoCuentaBancaria] = None
    numero_cuenta: str = Field(default="", max_length=50)
    horario: dict[DiaSemana, HorarioDia] = Field(default_factory=dict)


class NominaEmpleadoOut(BaseModel):
    staff_id: int
    nombre: str
    apellido: str
    rol: str
    activo: bool
    numero_documento: str
    tiene_perfil: bool
    tipo_contrato: TipoContrato
    tipo_pago: TipoPagoNomina
    salario_base: float
    valor_hora: float
    valor_dia: float
    eps: str
    afp: str
    arl: str
    fecha_ingreso: Optional[date] = None
    banco: str
    tipo_cuenta: Optional[TipoCuentaBancaria] = None
    numero_cuenta: str
    horario: dict[DiaSemana, HorarioDia] = Field(default_factory=dict)


class CorteDiaOut(BaseModel):
    staff_id: int
    nombre: str
    rol: str
    tipo_pago: TipoPagoNomina
    horas_programadas: float
    monto_sugerido: float
    pago_id: Optional[int] = None
    monto_pagado: Optional[float] = None
    notas: str = ""


class CortePagoIn(BaseModel):
    staff_id: int
    fecha: date
    monto: float = Field(ge=0)
    notas: str = Field(default="", max_length=300)


class CortePagoOut(BaseModel):
    id: int
    staff_id: int
    nombre: str
    fecha: date
    monto: float
    notas: str
    created_at: datetime


class NominaPeriodoIn(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    tipo: TipoPeriodoNomina = "quincenal"


class NominaPeriodoOut(BaseModel):
    id: int
    fecha_inicio: date
    fecha_fin: date
    tipo: TipoPeriodoNomina
    estado: EstadoPeriodoNomina
    total_empleados: int
    total_neto: float
    created_at: datetime
    cerrado_en: Optional[datetime] = None


class NominaCalcularIn(BaseModel):
    porcentaje_salud: float = Field(ge=0, le=100, default=4)
    porcentaje_pension: float = Field(ge=0, le=100, default=4)


class NominaDetalleOut(BaseModel):
    id: int
    periodo_id: int
    staff_id: int
    nombre: str
    rol: str
    salario_base: float
    dias_trabajados: float
    horas_extra: float
    bonificaciones: float
    propinas: float
    otros_descuentos: float
    salud: float
    pension: float
    total_devengado: float
    total_deducciones: float
    neto_pagar: float
    notas: str


class NominaDetalleUpdateIn(BaseModel):
    dias_trabajados: float = Field(ge=0, default=30)
    horas_extra: float = Field(ge=0, default=0)
    bonificaciones: float = Field(ge=0, default=0)
    propinas: float = Field(ge=0, default=0)
    otros_descuentos: float = Field(ge=0, default=0)
    salud: float = Field(ge=0, default=0)
    pension: float = Field(ge=0, default=0)
    notas: str = Field(default="", max_length=300)
