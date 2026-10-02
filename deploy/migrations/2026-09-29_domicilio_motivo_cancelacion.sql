-- Motivo que el negocio escribe al cancelar un domicilio ya aceptado (preparación o listo); vacío
-- en cancelaciones del propio cliente o del negocio antes de aceptar el pedido.
-- Run on the chefcontrol database.
ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS motivo_cancelacion text NOT NULL DEFAULT '';
