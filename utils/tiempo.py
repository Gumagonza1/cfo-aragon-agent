"""
utils/tiempo.py — Utilidades de fecha/hora centralizadas para GMT-7 (America/Hermosillo).
Todos los módulos del CFO deben importar de aquí en lugar de llamar datetime.now() directamente.
"""

from datetime import datetime, date
import pytz

ZONA = pytz.timezone("America/Hermosillo")


def ahora() -> datetime:
    """Datetime actual en GMT-7."""
    return datetime.now(ZONA)


def hoy() -> date:
    """Fecha actual en GMT-7."""
    return ahora().date()


def inicio_mes(anio: int, mes: int) -> datetime:
    """Primer instante del mes dado en GMT-7."""
    return ZONA.localize(datetime(anio, mes, 1, 0, 0, 0))


def fin_mes(anio: int, mes: int) -> datetime:
    """Último instante del mes dado en GMT-7 (último día a las 23:59:59)."""
    import calendar
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return ZONA.localize(datetime(anio, mes, ultimo_dia, 23, 59, 59))


def ts_ahora() -> str:
    """Timestamp ISO 8601 en GMT-7 para logs y respuestas API."""
    return ahora().isoformat()
