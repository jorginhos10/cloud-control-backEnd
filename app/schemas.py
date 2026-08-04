from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=150, alias="fullName")
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)

    model_config = {"populate_by_name": True}


class LoginIn(BaseModel):
    email: EmailStr
    password: str


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

    model_config = {"populate_by_name": True}


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


EstadoVenta = Literal["abierta", "en_preparacion", "lista", "cerrada", "cancelada"]
TipoVenta = Literal["mesa", "directa"]
MetodoPago = Literal["efectivo", "tarjeta", "transferencia", "mixto"]


class VentaCrearIn(BaseModel):
    mesa_id: Optional[int] = None


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
    notas: str
    metodo_pago: Optional[MetodoPago] = None
    pago_efectivo: float = 0
    pago_tarjeta: float = 0
    pago_transferencia: float = 0
    propina: float = 0
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime] = None
    items: list[VentaItemOut] = []


class VentaEstadoIn(BaseModel):
    estado: EstadoVenta


class VentaNotasIn(BaseModel):
    notas: str = Field(default="", max_length=500)


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


class CocinaItemOut(BaseModel):
    id: int
    nombre: str
    cantidad: int
    categoria: str


class CocinaOrdenOut(BaseModel):
    id: int
    tipo: TipoVenta
    estado: EstadoVenta
    notas: str
    fecha_apertura: datetime
    mesa_numero: Optional[int] = None
    mesa_nombre: Optional[str] = None
    mesa_zona: Optional[str] = None
    items: list[CocinaItemOut] = []


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


class MenuDigitalDetalleOut(MenuDigitalOut):
    items: list[MenuItemOut] = []


class PedidoItemIn(BaseModel):
    receta_id: int
    cantidad: int = Field(ge=1, default=1)


class PedidoIn(BaseModel):
    items: list[PedidoItemIn] = []


class PedidoOut(BaseModel):
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
    items: list[DomicilioItemIn] = []


class DomicilioInternoIn(DomicilioPedidoIn):
    valor_domicilio: Optional[float] = Field(default=None, ge=0)


class DomicilioEstadoIn(BaseModel):
    estado: EstadoDomicilio
    valor_domicilio: Optional[float] = Field(default=None, ge=0)


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
    estado: EstadoDomicilio
    total: float
    valor_domicilio: Optional[float] = None
    created_at: datetime
    updated_at: datetime
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
    cantidad_stock: float


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


MotivoPerdida = Literal["vencido", "danado", "robo", "error_cocina", "otro"]
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
    username: str = Field(min_length=3, max_length=50)
    nombre: str = Field(min_length=1, max_length=150)
    email: EmailStr
    rol: RolStaff = "mesero"
    password: str = Field(min_length=6, max_length=72)
    activo: bool = True


class UsuarioStaffUpdateIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
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
    email: str
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
