-- El chat del pedido ahora puede ir dirigido al restaurante o al domiciliario que lo reclamó.
-- 'para' marca el hilo al que pertenece cada mensaje; por defecto sigue siendo el restaurante
-- (el comportamiento de siempre) para que las filas existentes no cambien de hilo.
ALTER TABLE domicilio_chat ADD COLUMN IF NOT EXISTS para TEXT NOT NULL DEFAULT 'restaurante';
ALTER TABLE domicilio_chat DROP CONSTRAINT IF EXISTS domicilio_chat_para_check;
ALTER TABLE domicilio_chat ADD CONSTRAINT domicilio_chat_para_check CHECK (para = ANY (ARRAY['restaurante', 'domiciliario']));

-- 'de' era varchar(10): alcanzaba para 'cliente'/'admin' pero no para el nuevo valor
-- 'domiciliario' (12 caracteres).
ALTER TABLE domicilio_chat ALTER COLUMN de TYPE TEXT;

-- El check original solo permitía 'cliente'/'admin'; se reemplaza para sumar 'domiciliario'.
ALTER TABLE domicilio_chat DROP CONSTRAINT IF EXISTS domicilio_chat_de_check;
ALTER TABLE domicilio_chat ADD CONSTRAINT domicilio_chat_de_check CHECK (de = ANY (ARRAY['cliente', 'admin', 'domiciliario']));
