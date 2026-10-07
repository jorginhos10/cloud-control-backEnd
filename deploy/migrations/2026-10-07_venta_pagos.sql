-- Pagos parciales para "cuentas divididas": cada fila es lo que pagó una persona de la mesa.
-- Cuando la suma de montos alcanza el total de la venta, esta se cierra sola (mismo efecto que
-- /ventas/{id}/cobrar de un solo pago, pero en varios pasos), agregando el desglose por método
-- en ventas.pago_efectivo/pago_tarjeta/pago_transferencia/propina para que los reportes que ya
-- leen esas columnas sigan funcionando sin cambios.
CREATE TABLE IF NOT EXISTS venta_pagos (
    id BIGSERIAL PRIMARY KEY,
    venta_id BIGINT NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    metodo_pago TEXT NOT NULL,
    monto NUMERIC(12,2) NOT NULL,
    propina NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta_id ON venta_pagos (venta_id);
