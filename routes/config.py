"""
routes/config.py – Gestión de credenciales SAT y Gmail desde la app.
Actualiza el .env en disco y recarga os.environ sin reiniciar el servidor.
"""

import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])

ENV_PATH = Path(__file__).parent.parent / ".env"

# Campos editables y su clave en .env
_CAMPOS = {
    "sat_rfc":          "SAT_RFC",
    "sat_key_password": "SAT_KEY_PASSWORD",
    "email_user":       "EMAIL_USER",
    "email_pass":       "EMAIL_PASS",
    "imap_server":      "IMAP_SERVER",
}


class CredencialesUpdate(BaseModel):
    sat_rfc:          str | None = None
    sat_key_password: str | None = None
    email_user:       str | None = None
    email_pass:       str | None = None
    imap_server:      str | None = None


def _leer_env() -> dict:
    """Lee el .env y devuelve {clave: valor}."""
    env = {}
    if not ENV_PATH.exists():
        return env
    for linea in ENV_PATH.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, _, v = linea.partition("=")
            env[k.strip()] = v.strip()
    return env


def _escribir_env(env: dict) -> None:
    """Reescribe el .env preservando comentarios y orden."""
    contenido_original = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    nuevas_lineas = []
    claves_escritas = set()

    for linea in contenido_original.splitlines():
        stripped = linea.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in env:
                nuevas_lineas.append(f"{k}={env[k]}")
                claves_escritas.add(k)
                continue
        nuevas_lineas.append(linea)

    # Agregar claves nuevas que no estaban en el archivo
    for k, v in env.items():
        if k not in claves_escritas:
            nuevas_lineas.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(nuevas_lineas) + "\n", encoding="utf-8")


def _mask(valor: str) -> str:
    """Enmascara credenciales: muestra primeros 2 + *** + últimos 2."""
    if not valor or len(valor) <= 4:
        return "***"
    return valor[:2] + "*" * (len(valor) - 4) + valor[-2:]


@router.get("/credenciales")
def obtener_credenciales():
    """Devuelve los valores actuales (enmascarados) de las credenciales."""
    return {
        "sat_rfc":          os.getenv("SAT_RFC", ""),
        "sat_key_password": _mask(os.getenv("SAT_KEY_PASSWORD", "")),
        "email_user":       os.getenv("EMAIL_USER", ""),
        "email_pass":       _mask(os.getenv("EMAIL_PASS", "")),
        "imap_server":      os.getenv("IMAP_SERVER", "imap.gmail.com"),
    }


@router.put("/credenciales")
def actualizar_credenciales(body: CredencialesUpdate):
    """
    Actualiza credenciales SAT y/o Gmail.
    Escribe en .env y recarga os.environ inmediatamente.
    """
    actualizaciones = {}

    for campo_python, clave_env in _CAMPOS.items():
        valor = getattr(body, campo_python, None)
        if valor is not None:
            valor = valor.strip()
            if valor:
                actualizaciones[clave_env] = valor

    if not actualizaciones:
        raise HTTPException(400, "No se enviaron credenciales para actualizar")

    # Leer .env actual, aplicar cambios, guardar
    env_actual = _leer_env()
    env_actual.update(actualizaciones)
    _escribir_env(env_actual)

    # Recargar en el proceso actual (sin reiniciar)
    for clave, valor in actualizaciones.items():
        os.environ[clave] = valor

    return {
        "actualizado": list(actualizaciones.keys()),
        "nota": "Credenciales activas inmediatamente. El .env quedo guardado para el proximo reinicio.",
    }
