import hashlib
import hmac
import secrets
import time

import jwt

PBKDF2_ITERATIONS = 260_000
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60  # 8 horas


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _algorithm, iterations, salt, hash_hex = stored_hash.split("$")
        iterations = int(iterations)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


def create_token(secret: str, user_id: int, email: str, rol: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "rol": rol,
        "iat": now,
        "exp": now + TOKEN_LIFETIME_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
