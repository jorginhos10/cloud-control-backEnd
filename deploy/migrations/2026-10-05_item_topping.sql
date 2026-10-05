-- Cada ítem de una venta o un domicilio puede llevar un topping elegido (si la receta tiene
-- toppings asociados). topping_nombre es una foto del nombre al momento de pedir, igual que ya
-- se hace con el nombre de la receta — si el topping se renombra o se borra despues, el pedido
-- ya hecho no cambia.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS topping_id bigint REFERENCES toppings(id);
ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS topping_nombre varchar(80);
ALTER TABLE domicilio_items ADD COLUMN IF NOT EXISTS topping_id bigint REFERENCES toppings(id);
ALTER TABLE domicilio_items ADD COLUMN IF NOT EXISTS topping_nombre varchar(80);
