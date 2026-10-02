-- Permite asociar una venta a un cliente ya registrado (para la factura/comanda impresa
-- y para llevar el historial de compras por cliente). Nula por defecto: la mayoría de
-- ventas de mostrador no identifican al cliente.
-- Run on the chefcontrol database.
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cliente_id integer REFERENCES clientes(id) ON DELETE SET NULL;
