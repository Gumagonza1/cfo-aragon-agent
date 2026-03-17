"""
routes/contabilidad.py – Ingresos/gastos manuales + P&L y Balance con Claude.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from db.database import get_db
from db.models import Ingreso, Gasto
from agents.cfo_agent import generar_estado_resultados, generar_balance, chat_cfo

router = APIRouter(prefix="/api/contabilidad", tags=["contabilidad"])

TIPOS_INGRESO = [
    # Cuentas detalladas (app)
    "ventas_efectivo", "ventas_transferencia", "ventas_tarjeta", "ventas_link",
    "retiro_banco", "otros_ingresos",
    # Tipos legacy (job nocturno y resolverPendiente)
    "ventas", "otros",
]
TIPOS_GASTO = [
    # Costo de ventas
    "costo_venta", "empaque",
    # Nomina
    "nomina", "imss",
    # Gastos fijos
    "renta", "luz_gas_agua", "tel_internet",
    # Gastos operativos
    "mantenimiento", "transporte", "publicidad", "limpieza",
    # Proveedores
    "pago_proveedor_ef", "pago_proveedor_tr", "pago_proveedor_td",
    # Administración
    "honorarios", "papeleria",
    # Crédito / banco
    "pago_credito", "deposito_banco",
    # Otros
    "otros_gastos",
    # Tipos legacy (job nocturno y resolverPendiente)
    "operativo", "materia_prima", "servicios", "otros",
]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class IngresoIn(BaseModel):
    fecha:    str           # YYYY-MM-DD
    concepto: str
    tipo:     str = "ventas"
    monto:    float
    notas:    str = ""

class GastoIn(BaseModel):
    fecha:     str
    concepto:  str
    tipo:      str = "otros_gastos"
    monto:     float
    deducible: int = 1      # 0 o 1
    notas:     str = ""

class ChatCfoRequest(BaseModel):
    pregunta: str
    periodo:  str = None

class EstadoRequest(BaseModel):
    desde: str   # YYYY-MM-DD
    hasta: str


# ─── Ingresos ─────────────────────────────────────────────────────────────────

@router.get("/ingresos")
def listar_ingresos(desde: str = None, hasta: str = None, db: Session = Depends(get_db)):
    q = db.query(Ingreso).order_by(Ingreso.fecha.desc())
    if desde: q = q.filter(Ingreso.fecha >= desde)
    if hasta: q = q.filter(Ingreso.fecha <= hasta)
    return q.limit(200).all()


@router.post("/ingresos")
def crear_ingreso(data: IngresoIn, db: Session = Depends(get_db)):
    if data.tipo not in TIPOS_INGRESO:
        raise HTTPException(400, f"tipo debe ser uno de: {TIPOS_INGRESO}")
    if data.monto <= 0:
        raise HTTPException(400, "monto debe ser positivo")
    item = Ingreso(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/ingresos/{ingreso_id}")
def eliminar_ingreso(ingreso_id: int, db: Session = Depends(get_db)):
    item = db.query(Ingreso).filter(Ingreso.id == ingreso_id).first()
    if not item:
        raise HTTPException(404, "Ingreso no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ─── Gastos ───────────────────────────────────────────────────────────────────

@router.get("/gastos")
def listar_gastos(desde: str = None, hasta: str = None, db: Session = Depends(get_db)):
    q = db.query(Gasto).order_by(Gasto.fecha.desc())
    if desde: q = q.filter(Gasto.fecha >= desde)
    if hasta: q = q.filter(Gasto.fecha <= hasta)
    return q.limit(200).all()


@router.post("/gastos")
def crear_gasto(data: GastoIn, db: Session = Depends(get_db)):
    if data.tipo not in TIPOS_GASTO:
        raise HTTPException(400, f"tipo debe ser uno de: {TIPOS_GASTO}")
    if data.monto <= 0:
        raise HTTPException(400, "monto debe ser positivo")
    item = Gasto(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int, db: Session = Depends(get_db)):
    item = db.query(Gasto).filter(Gasto.id == gasto_id).first()
    if not item:
        raise HTTPException(404, "Gasto no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ─── Análisis CFO ─────────────────────────────────────────────────────────────

@router.post("/estado-resultados")
async def estado_resultados(req: EstadoRequest, db: Session = Depends(get_db)):
    """Claude genera el Estado de Resultados del período."""
    ingresos = db.query(Ingreso).filter(
        Ingreso.fecha >= req.desde, Ingreso.fecha <= req.hasta
    ).all()
    gastos = db.query(Gasto).filter(
        Gasto.fecha >= req.desde, Gasto.fecha <= req.hasta
    ).all()

    ingresos_dict = [{"concepto": i.concepto, "tipo": i.tipo, "monto": i.monto, "fecha": i.fecha} for i in ingresos]
    gastos_dict   = [{"concepto": g.concepto, "tipo": g.tipo, "monto": g.monto, "fecha": g.fecha, "deducible": g.deducible} for g in gastos]

    analisis = await generar_estado_resultados(ingresos_dict, gastos_dict, f"{req.desde} a {req.hasta}")

    return {
        "periodo":       f"{req.desde} a {req.hasta}",
        "total_ingresos": sum(i.monto for i in ingresos),
        "total_gastos":   sum(g.monto for g in gastos),
        "analisis":       analisis,
    }


@router.post("/balance")
async def balance_general(req: EstadoRequest, db: Session = Depends(get_db)):
    """Claude genera el Balance General."""
    from db.models import InventarioItem
    ingresos  = db.query(Ingreso).filter(Ingreso.fecha >= req.desde, Ingreso.fecha <= req.hasta).all()
    gastos    = db.query(Gasto).filter(Gasto.fecha >= req.desde, Gasto.fecha <= req.hasta).all()
    inventario = db.query(InventarioItem).all()

    ingresos_dict  = [{"concepto": i.concepto, "monto": i.monto} for i in ingresos]
    gastos_dict    = [{"concepto": g.concepto, "monto": g.monto} for g in gastos]
    inv_dict       = [{"nombre": i.nombre, "cantidad": i.cantidad, "costo_unitario": i.costo_unitario} for i in inventario]

    analisis = await generar_balance(ingresos_dict, gastos_dict, inv_dict, req.hasta)
    return {"periodo": req.hasta, "analisis": analisis}


@router.post("/chat")
async def chat(req: ChatCfoRequest, db: Session = Depends(get_db)):
    """Chat con el agente CFO."""
    # Dar contexto básico de la BD
    total_ing = db.query(Ingreso).count()
    total_gas = db.query(Gasto).count()
    contexto  = {"registros_ingresos": total_ing, "registros_gastos": total_gas, "periodo": req.periodo}

    respuesta = await chat_cfo(req.pregunta, contexto)
    return {"respuesta": respuesta}
