-- Sabores ahora también pueden tener foto, igual que los toppings.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE sabores ADD COLUMN IF NOT EXISTS foto_url TEXT;
ALTER TABLE sabores ADD COLUMN IF NOT EXISTS foto_thumb_url TEXT;
