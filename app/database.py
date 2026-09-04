import os

import pg8000.native as pg8000


def get_connection() -> pg8000.Connection:
    return pg8000.Connection(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def get_superadmin_connection() -> pg8000.Connection:
    """Read-only access to the SuperAdmin database, for the platform-wide
    marketplace catalog curated there (marketplace_productos)."""
    return pg8000.Connection(
        host=os.environ["SUPERADMIN_DB_HOST"],
        port=int(os.environ.get("SUPERADMIN_DB_PORT", "5432")),
        database=os.environ["SUPERADMIN_DB_NAME"],
        user=os.environ["SUPERADMIN_DB_USER"],
        password=os.environ["SUPERADMIN_DB_PASSWORD"],
    )
