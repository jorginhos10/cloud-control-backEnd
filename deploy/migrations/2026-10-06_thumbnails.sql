-- Listados (GET /recetas, GET /toppings) ahora devuelven una miniatura liviana en vez de la
-- foto completa, para no arrastrar varios MB de base64 solo para pintar thumbnails de 48px.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE recetas ADD COLUMN IF NOT EXISTS imagen_thumb_url TEXT;
ALTER TABLE toppings ADD COLUMN IF NOT EXISTS foto_thumb_url TEXT;
