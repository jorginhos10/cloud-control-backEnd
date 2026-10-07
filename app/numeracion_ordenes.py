"""Numeración de órdenes ("SS-20260907-0248"), portada del viejo ChefControl en PHP
(ComercioModel::calcularIniciales / obtenerCodigoFacturacion y ventaModel::registrarVenta)."""

import uuid
from datetime import date

from pg8000.exceptions import DatabaseError

UNIQUE_VIOLATION = "23505"

STOPWORDS = {"el", "la", "los", "las", "de", "del", "y", "e"}


def calcular_iniciales(nombre: str) -> str:
    """Convierte el nombre del negocio en 2 iniciales. Ignora conectores cortos (el, la, los,
    las, de, del, y, e) solo si al quitarlos quedan al menos 2 palabras útiles (ej. "El Turrón
    de Azúcar" -> "Turrón", "Azúcar" -> TA); si no, usa las palabras originales sin filtrar (ej.
    "El Turrón" -> "El", "Turrón" -> ET). Una sola palabra usa sus 2 primeras letras."""
    palabras = [p for p in nombre.strip().split() if p]
    if not palabras:
        return "CC"

    filtradas = [p for p in palabras if p.lower() not in STOPWORDS]
    usar = filtradas if len(filtradas) >= 2 else palabras

    iniciales = "".join(p[0].upper() for p in usar[:2])
    if len(iniciales) < 2:
        iniciales = usar[0][:2].upper()
    return iniciales or "CC"


def obtener_codigo_facturacion(conn, usuario_id: int) -> str:
    """Código corto y único por negocio (ej. "SS"), asignado la primera vez a partir del
    nombre y persistido para que no vuelva a cambiar. Si ya está tomado por otro tenant, le
    suma un sufijo numérico (SS2, SS3...)."""
    rows = conn.run("SELECT codigo_facturacion FROM usuarios WHERE id = :id", id=usuario_id)
    actual = rows[0][0] if rows else None
    if actual:
        return actual

    negocio_rows = conn.run("SELECT nombre FROM negocios WHERE usuario_id = :id", id=usuario_id)
    nombre = negocio_rows[0][0] if negocio_rows and negocio_rows[0][0] else "Negocio"
    base = calcular_iniciales(nombre)

    codigo = base
    sufijo = 1
    while True:
        try:
            conn.run("UPDATE usuarios SET codigo_facturacion = :c WHERE id = :id", c=codigo, id=usuario_id)
            return codigo
        except DatabaseError as exc:
            if not (exc.args and exc.args[0].get("C") == UNIQUE_VIOLATION):
                raise
            sufijo += 1
            codigo = f"{base}{sufijo}"
            if sufijo > 50:
                codigo = f"{base}{uuid.uuid4().hex[:6]}"  # salvaguarda extrema, no debería llegar aquí


def generar_numero_orden(conn, usuario_id: int) -> str:
    """{iniciales}-{AAAAMMDD}-{consecutivo de 4 dígitos}. El consecutivo es la cantidad total
    histórica de ventas del negocio + 1 (no se reinicia por día; la fecha solo acompaña)."""
    count = conn.run("SELECT COUNT(*) FROM ventas WHERE usuario_id = :uid", uid=usuario_id)[0][0]
    codigo = obtener_codigo_facturacion(conn, usuario_id)
    return f"{codigo}-{date.today().strftime('%Y%m%d')}-{count + 1:04d}"
