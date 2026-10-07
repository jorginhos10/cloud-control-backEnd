-- Un topping ahora puede llevar insumos reales (ej. "Tocineta extra" consume bacon del
-- inventario), igual que ya pasa con las recetas vía receta_insumos. Sin esto, vender un
-- topping no descontaba ningún stock aunque sí consumiera insumos de verdad.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
CREATE TABLE IF NOT EXISTS topping_insumos (
    id BIGSERIAL PRIMARY KEY,
    id_topping BIGINT NOT NULL REFERENCES toppings(id) ON DELETE CASCADE,
    id_insumo BIGINT NOT NULL REFERENCES insumos(id),
    cantidad NUMERIC(10,3) NOT NULL,
    UNIQUE (id_topping, id_insumo)
);
