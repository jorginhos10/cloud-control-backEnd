-- Nuevo estado "entregada": el mesero/cocina lo usa para marcar que la comida ya se sirvió
-- en la mesa, sin cerrar la cuenta (la mesa puede seguir pidiendo). Antes de esto, una orden
-- "lista" se quedaba para siempre en el tablero de cocina hasta que se cobrara la cuenta
-- completa, a veces horas despues.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE ventas DROP CONSTRAINT ventas_estado_check;
ALTER TABLE ventas ADD CONSTRAINT ventas_estado_check
    CHECK (estado::text = ANY (ARRAY['abierta', 'en_preparacion', 'lista', 'entregada', 'cerrada', 'cancelada']::text[]));
