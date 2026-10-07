-- Cuántos sabores/toppings distintos puede elegir el cliente para este producto en un mismo
-- pedido. NULL = sin límite (puede elegir todos los que tenga el producto). Por defecto 1, que
-- es el comportamiento actual (una sola elección).
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE recetas ADD COLUMN IF NOT EXISTS max_sabores INTEGER DEFAULT 1;
ALTER TABLE recetas ADD COLUMN IF NOT EXISTS max_toppings INTEGER DEFAULT 1;
