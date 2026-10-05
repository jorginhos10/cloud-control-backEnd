-- Un topping puede costar distinto (o ser gratis) según el producto al que se asocie, no un
-- valor fijo global: el valor adicional vive en la asociación receta-topping, no en el topping.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE receta_toppings ADD COLUMN IF NOT EXISTS precio_adicional numeric(12,2) NOT NULL DEFAULT 0;
