-- A diferencia del resto de tablas del sistema, nomina_periodos y nomina_pagos_diarios se crearon
-- sin índice en usuario_id (la columna de tenant que usa cada consulta de este módulo).
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
CREATE INDEX IF NOT EXISTS idx_nomina_periodos_usuario ON nomina_periodos (usuario_id);
CREATE INDEX IF NOT EXISTS idx_nomina_pagos_diarios_usuario_fecha ON nomina_pagos_diarios (usuario_id, fecha);
