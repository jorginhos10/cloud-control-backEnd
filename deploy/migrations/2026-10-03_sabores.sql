-- Catálogo de sabores/variantes por negocio (ej. "Fresa", "Chocolate", "Picante") y su
-- asociación muchos-a-muchos con recetas, para el módulo de Sabores en Configuraciones.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
CREATE TABLE IF NOT EXISTS sabores (
    id bigserial PRIMARY KEY,
    usuario_id bigint NOT NULL REFERENCES usuarios(id),
    nombre varchar(80) NOT NULL,
    activo boolean NOT NULL DEFAULT true,
    fecha_creacion timestamptz NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, nombre)
);

CREATE TABLE IF NOT EXISTS receta_sabores (
    id bigserial PRIMARY KEY,
    id_receta bigint NOT NULL REFERENCES recetas(id) ON DELETE CASCADE,
    id_sabor bigint NOT NULL REFERENCES sabores(id) ON DELETE CASCADE,
    UNIQUE (id_receta, id_sabor)
);
