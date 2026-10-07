-- Foto por topping (igual que recetas.imagen_url: data URL base64, se comprime en el navegador
-- antes de subir). Se muestra en la página de Toppings y en el selector de toppings al pedir.
ALTER TABLE toppings ADD COLUMN IF NOT EXISTS foto_url TEXT;
