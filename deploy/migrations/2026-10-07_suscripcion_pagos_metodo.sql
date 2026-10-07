-- Pago de suscripción por Nequi (llave del negocio + código corto de referencia), además del
-- pago por Wompi que ya existía. No hay integración con la API de Nequi: el cliente paga
-- manualmente desde su app y el SuperAdmin confirma el pago a mano viendo ese código.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE suscripcion_pagos ADD COLUMN IF NOT EXISTS metodo TEXT NOT NULL DEFAULT 'wompi';
