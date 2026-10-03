-- Cada ítem de una venta o un domicilio puede llevar un sabor elegido (si la receta tiene
-- sabores asociados). sabor_nombre es una foto del nombre al momento de pedir, igual que ya
-- se hace con el nombre de la receta — si el sabor se renombra o se borra despues, el pedido
-- ya hecho no cambia.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS sabor_id bigint REFERENCES sabores(id);
ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS sabor_nombre varchar(80);
ALTER TABLE domicilio_items ADD COLUMN IF NOT EXISTS sabor_id bigint REFERENCES sabores(id);
ALTER TABLE domicilio_items ADD COLUMN IF NOT EXISTS sabor_nombre varchar(80);
