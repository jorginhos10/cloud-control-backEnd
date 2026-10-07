-- Un sabor puede costar distinto (o ser gratis) según el producto al que se asocie, no un
-- valor fijo global: el valor adicional vive en la asociación receta-sabor, no en el sabor,
-- igual que ya pasa con los toppings (ver 2026-10-05_topping_precio_adicional.sql).
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE receta_sabores ADD COLUMN IF NOT EXISTS precio_adicional numeric(12,2) NOT NULL DEFAULT 0;
