from app.database import get_connection, get_superadmin_connection

MONEDA_POR_DEFECTO = "USD"


def moneda_de_cuenta(tenant_id: int) -> str:
    """Currency of an account, derived (never chosen): the currency of the region of the country
    where it signed up. Accounts whose country could not be detected at signup (private IPs, older
    accounts) use the country of their plan instead; if that region isn't configured either, the
    plan's own currency, and finally USD."""
    conn = get_connection()
    try:
        rows = conn.run("SELECT pais, plan_id FROM usuarios WHERE id = :id", id=tenant_id)
    finally:
        conn.close()
    pais, plan_id = rows[0] if rows else (None, None)

    try:
        sconn = get_superadmin_connection()
    except Exception:
        return MONEDA_POR_DEFECTO
    try:
        plan = sconn.run("SELECT pais, moneda FROM planes WHERE id = :id", id=plan_id)[0] if plan_id else None
        codigo_pais = (pais or (plan[0] if plan else None) or "").strip().upper()
        if codigo_pais:
            region = sconn.run(
                "SELECT codigo_moneda FROM regiones WHERE codigo_pais = :p AND activo = true", p=codigo_pais,
            )
            if region:
                return region[0][0]
        if plan and plan[1]:
            return plan[1]
        return MONEDA_POR_DEFECTO
    finally:
        sconn.close()
