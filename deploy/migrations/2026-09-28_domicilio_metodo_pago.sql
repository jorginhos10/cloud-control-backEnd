-- Cómo pagará el cliente su domicilio (efectivo, tarjeta o transferencia). Vacío en los pedidos anteriores.
-- Run on the chefcontrol database.
ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS metodo_pago varchar(20) NOT NULL DEFAULT '';
