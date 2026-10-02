-- Shipping charged on a marketplace order (sum of the shipping price of each product line).
-- total = subtotal - descuento + envio. Run on the chefcontrol database.
ALTER TABLE marketplace_pedidos ADD COLUMN IF NOT EXISTS envio numeric(12, 2) NOT NULL DEFAULT 0;
