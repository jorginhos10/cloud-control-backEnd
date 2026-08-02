import os

from fastapi import APIRouter, HTTPException

from app.database import get_connection
from app.schemas import LoginRequest, LoginResponse, RegistroRequest, UsuarioOut
from app.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/registro", response_model=UsuarioOut, status_code=201)
def registro(payload: RegistroRequest):
    username = payload.username.strip()
    nombre = payload.nombre.strip()
    email = payload.email.strip().lower()

    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"Error de conexión a la base de datos: {exc}")
        raise HTTPException(status_code=500, detail="No se pudo conectar a la base de datos")

    try:
        existe = conn.run(
            "SELECT id FROM usuarios WHERE username = :u OR email = :e",
            u=username,
            e=email,
        )
        if existe:
            raise HTTPException(status_code=409, detail="El usuario o email ya está registrado")

        password_hash = hash_password(payload.password)

        fila = conn.run(
            """
            INSERT INTO usuarios (username, nombre, email, password_hash, rol)
            VALUES (:username, :nombre, :email, :password_hash, :rol)
            RETURNING id, username, nombre, email, rol, activo, fecha_creacion
            """,
            username=username,
            nombre=nombre,
            email=email,
            password_hash=password_hash,
            rol=payload.rol,
        )
        row = fila[0]
        return UsuarioOut(
            id=row[0],
            username=row[1],
            nombre=row[2],
            email=row[3],
            rol=row[4],
            activo=row[5],
            fecha_creacion=row[6].isoformat() if row[6] else None,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Error en registro: {exc}")
        raise HTTPException(status_code=500, detail="Error interno al registrar el usuario")
    finally:
        conn.close()


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    email = payload.email.strip().lower()

    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"Error de conexión a la base de datos: {exc}")
        raise HTTPException(status_code=500, detail="No se pudo conectar a la base de datos")

    try:
        filas = conn.run(
            """
            SELECT id, username, nombre, email, password_hash, rol, activo, propietario
            FROM usuarios
            WHERE email = :email
            """,
            email=email,
        )

        if not filas:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        uid, username, nombre, email_db, password_hash, rol, activo, propietario = filas[0]

        if not verify_password(payload.password, password_hash):
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not activo:
            raise HTTPException(status_code=403, detail="Este usuario está inactivo")

        conn.run("UPDATE usuarios SET ultimo_login = now() WHERE id = :id", id=uid)

        token = create_token(os.environ["JWT_SECRET"], uid, email_db, rol)

        return LoginResponse(
            token=token,
            usuario=UsuarioOut(
                id=uid,
                username=username,
                nombre=nombre,
                email=email_db,
                rol=rol,
                activo=True,
                propietario=propietario,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Error en login: {exc}")
        raise HTTPException(status_code=500, detail="Error interno al iniciar sesión")
    finally:
        conn.close()
