-- Numeración de órdenes tipo "SS-20260907-0248" (iniciales del negocio + fecha + consecutivo),
-- portada del viejo ChefControl en PHP (ComercioModel::obtenerCodigoFacturacion +
-- ventaModel::registrarVenta). El código se guarda en usuarios (no en negocios) porque no
-- todos los tenants tienen fila en negocios todavía (onboarding incompleto).
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS numero_orden TEXT;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS codigo_facturacion TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_codigo_facturacion ON usuarios (codigo_facturacion);
