from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

Rol = Literal["admin", "cocina", "inventario", "mesero"]


class RegistroRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    nombre: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    rol: Rol = "mesero"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UsuarioOut(BaseModel):
    id: int
    username: str
    nombre: str
    email: str
    rol: str
    activo: bool
    propietario: Optional[bool] = None
    fecha_creacion: Optional[str] = None


class LoginResponse(BaseModel):
    token: str
    usuario: UsuarioOut
