"""
main.py – CFO Aragón Agent
FastAPI server en puerto 3002.

Agente dual:
  - Gemini: descarga CFDIs del SAT, parsea XMLs
  - Claude: análisis contable, fiscal, P&L, balance, inventario
"""

import io
import os
import sys

# Forzar UTF-8 en stdout/stderr (necesario en Windows con cp1252)
# Evita UnicodeEncodeError cuando librerías externas imprimen emojis.
if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer') and sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db.database import init_db
from utils.tiempo import ts_ahora
from routes.impuestos    import router as impuestos_router
from routes.contabilidad import router as contabilidad_router
from routes.inventario   import router as inventario_router
from routes.config       import router as config_router

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CFO Aragón Agent",
    description="Agente CFO dual (Gemini + Claude) para análisis fiscal y financiero de Tacos Aragón.",
    version="1.0.0",
    docs_url="/docs",
)

# ─── Rate limiting ────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ─── Auth middleware ──────────────────────────────────────────────────────────

API_TOKEN = os.getenv("API_TOKEN", "")
RUTAS_PUBLICAS = {"/health", "/docs", "/openapi.json"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in RUTAS_PUBLICAS or request.url.path.startswith("/docs"):
        return await call_next(request)
    token = request.headers.get("x-api-token") or request.query_params.get("token")
    if not token or token != API_TOKEN:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    return await call_next(request)

# ─── Log de peticiones ────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[{ts_ahora()}] {request.method} {request.url.path} | IP: {request.client.host}")
    return await call_next(request)

# ─── Rutas v1 (con versión explícita) ─────────────────────────────────────────
# Los routers tienen prefix="/api/..." por compatibilidad con el orquestador.
# Se montan también bajo /api/v1/... para que clientes nuevos usen rutas versionadas.

app.include_router(impuestos_router)
app.include_router(contabilidad_router)
app.include_router(inventario_router)
app.include_router(config_router)

# Alias /api/v1/... — mismos routers, distinto prefix
from fastapi import APIRouter as _AR

def _versionar(router, prefix_original: str):
    """Monta el mismo router bajo /api/v1/... además del path original."""
    prefijo_v1 = prefix_original.replace("/api/", "/api/v1/", 1)
    app.include_router(router, prefix=prefijo_v1)

_versionar(impuestos_router,    "/api/impuestos")
_versionar(contabilidad_router, "/api/contabilidad")
_versionar(inventario_router,   "/api/inventario")
_versionar(config_router,       "/api/config")

# Chat CFO libre
from fastapi import APIRouter
from pydantic import BaseModel
from agents.cfo_agent import chat_cfo

cfo_router = APIRouter(prefix="/api/cfo", tags=["cfo"])

class CfoChat(BaseModel):
    pregunta: str

@cfo_router.post("/chat")
async def cfo_chat_endpoint(req: CfoChat):
    respuesta = await chat_cfo(req.pregunta)
    return {"respuesta": respuesta}

app.include_router(cfo_router)

# ─── Contador de peticiones en vuelo (para health check) ─────────────────────
# Incrementa cuando llega una petición autenticada, decrementa al responder.
# Si supera el umbral, el health check lo reporta como advertencia.
_peticiones_activas = 0
_UMBRAL_COLA = 10

@app.middleware("http")
async def contar_peticiones(request: Request, call_next):
    global _peticiones_activas
    rutas_ignorar = {"/health", "/docs", "/openapi.json"}
    if request.url.path not in rutas_ignorar and not request.url.path.startswith("/docs"):
        _peticiones_activas += 1
    try:
        response = await call_next(request)
    finally:
        if request.url.path not in rutas_ignorar and not request.url.path.startswith("/docs"):
            _peticiones_activas -= 1
    return response


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    advertencia = None
    if _peticiones_activas > _UMBRAL_COLA:
        advertencia = (
            f"{_peticiones_activas} peticiones activas simultáneas — "
            "posible orquestador enviando solicitudes sin esperar respuesta"
        )
        print(f"[CFO] ⚠️  {advertencia}")

    return {
        "status":           "ok",
        "nombre":           "CFO Aragón Agent",
        "version":          "1.0.0",
        "agentes":          ["Gemini (SAT/parseo)", "Claude (análisis fiscal/financiero)"],
        "timestamp":        ts_ahora(),
        "peticiones_activas": _peticiones_activas,
        **({"advertencia": advertencia} if advertencia else {}),
    }

# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()
    port = os.getenv("PORT", 3002)
    print(f"[OK] CFO Aragon Agent corriendo en puerto {port}")
    print(f"     Gemini: descarga SAT + parseo XML")
    print(f"     Claude: analisis fiscal + contabilidad")
    print(f"     Docs:   http://localhost:{port}/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 3002)), reload=False)
