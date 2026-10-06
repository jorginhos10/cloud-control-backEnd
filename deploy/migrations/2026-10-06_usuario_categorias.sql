-- Categorías de receta que un usuario de cocina tiene asignadas: si un cocinero tiene al menos
-- una asignada, la pantalla de Cocina le filtra los ítems a solo esas categorías (los demás
-- roles, o un cocinero sin asignaciones, siguen viendo todo como antes).
CREATE TABLE IF NOT EXISTS usuario_categorias (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    categoria_id INTEGER NOT NULL REFERENCES receta_categorias(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, categoria_id)
);
