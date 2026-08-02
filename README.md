# ChefControl backend (FastAPI)

API con dos endpoints:
- `POST /api/auth/registro`
- `POST /api/auth/login`
- `GET /health` (para verificar que el servicio está vivo)

## Desarrollo local

```powershell
python -m venv venv
./venv/Scripts/activate
pip install -r requirements.txt
copy .env.example .env   # y edita los valores
python -m uvicorn app.main:app --reload --port 8000
```

Prueba con `curl`:
```bash
curl -X POST http://localhost:8000/api/auth/registro \
  -H "Content-Type: application/json" \
  -d '{"username":"ana.cocina","nombre":"Ana Torres","email":"ana@chefcontrol.com","password":"clave12345","rol":"cocina"}'
```

---

## Desplegar en el servidor Ubuntu (con nginx)

### 1. Copiar el proyecto al servidor

Desde tu PC (reemplaza `usuario@tu-servidor`):
```bash
scp -r backend usuario@tu-servidor:/home/usuario/chefcontrol-backend
```
O usa `git clone` si ya subiste el repo.

### 2. En el servidor: Python, venv y dependencias

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
cd /home/usuario/chefcontrol-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Variables de entorno

Crea `/home/usuario/chefcontrol-backend/.env` (mismo formato que `.env.example`) con los datos reales de tu base — RDS o la que estés usando en producción — y un `JWT_SECRET` largo y aleatorio (genera uno con `openssl rand -hex 32`).

### 4. Servicio systemd (para que corra siempre, con auto-reinicio)

Crea `/etc/systemd/system/chefcontrol-backend.service`:

```ini
[Unit]
Description=ChefControl FastAPI backend
After=network.target

[Service]
User=usuario
WorkingDirectory=/home/usuario/chefcontrol-backend
EnvironmentFile=/home/usuario/chefcontrol-backend/.env
ExecStart=/home/usuario/chefcontrol-backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

Actívalo:
```bash
sudo systemctl daemon-reload
sudo systemctl enable chefcontrol-backend
sudo systemctl start chefcontrol-backend
sudo systemctl status chefcontrol-backend   # debe decir "active (running)"
```

Nota: uvicorn escucha en `127.0.0.1:8000` — **no** en `0.0.0.0` — así solo nginx (en la misma máquina) puede hablarle directamente; el mundo exterior entra por nginx.

### 5. Configurar nginx como proxy reverso

Crea `/etc/nginx/sites-available/chefcontrol-backend`:

```nginx
server {
    listen 80;
    server_name tu-dominio-o-ip;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Actívalo y recarga nginx:
```bash
sudo ln -s /etc/nginx/sites-available/chefcontrol-backend /etc/nginx/sites-enabled/
sudo nginx -t   # valida la config antes de recargar
sudo systemctl reload nginx
```

### 6. Probar desde afuera

```bash
curl -X POST http://tu-dominio-o-ip/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@chefcontrol.com","password":"clave12345"}'
```

### 7. (Recomendado) HTTPS con Let's Encrypt

Si tienes un dominio apuntando al servidor:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
```
Certbot ajusta automáticamente la config de nginx para servir por HTTPS.

## Ver logs si algo falla

```bash
sudo journalctl -u chefcontrol-backend -f
```
Ahí verás cualquier traceback de Python en tiempo real — es el equivalente a los CloudWatch Logs que usábamos con Lambda.
