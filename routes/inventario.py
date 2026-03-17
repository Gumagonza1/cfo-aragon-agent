"""
routes/inventario.py – CRUD de inventario + análisis CFO.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from db.database import get_db
from db.models import InventarioItem
from agents.cfo_agent import analizar_inventario

router = APIRouter(prefix="/api/inventario", tags=["inventario"])

CATEGORIAS = ["insumo", "producto", "herramienta", "otros"]


class ItemIn(BaseModel):
    nombre:         str
    categoria:      str = "insumo"
    unidad:         str = "pza"
    cantidad:       float = 0
    costo_unitario: float = 0
    minimo:         float = 0

class ActualizarCantidad(BaseModel):
    cantidad: float


@router.get("/")
def listar(categoria: str = None, db: Session = Depends(get_db)):
    q = db.query(InventarioItem).order_by(InventarioItem.nombre)
    if categoria:
        q = q.filter(InventarioItem.categoria == categoria)
    items = q.all()

    # Marcar alertas
    resultado = []
    for item in items:
        d = {
            "id":             item.id,
            "nombre":         item.nombre,
            "categoria":      item.categoria,
            "unidad":         item.unidad,
            "cantidad":       item.cantidad,
            "costo_unitario": item.costo_unitario,
            "valor_total":    item.cantidad * item.costo_unitario,
            "minimo":         item.minimo,
            "alerta":         item.minimo > 0 and item.cantidad < item.minimo,
            "actualizado":    item.actualizado,
        }
        resultado.append(d)
    return resultado


@router.post("/")
def crear_item(data: ItemIn, db: Session = Depends(get_db)):
    if data.categoria not in CATEGORIAS:
        raise HTTPException(400, f"categoria debe ser: {CATEGORIAS}")
    existente = db.query(InventarioItem).filter(InventarioItem.nombre == data.nombre).first()
    if existente:
        raise HTTPException(409, f"Ya existe un item con nombre '{data.nombre}'")
    item = InventarioItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}")
def actualizar_item(item_id: int, data: ItemIn, db: Session = Depends(get_db)):
    item = db.query(InventarioItem).filter(InventarioItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item no encontrado")
    for field, value in data.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}/cantidad")
def actualizar_cantidad(item_id: int, data: ActualizarCantidad, db: Session = Depends(get_db)):
    item = db.query(InventarioItem).filter(InventarioItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item no encontrado")
    item.cantidad = data.cantidad
    db.commit()
    return {"id": item.id, "nombre": item.nombre, "cantidad": item.cantidad, "alerta": item.minimo > 0 and item.cantidad < item.minimo}


@router.delete("/{item_id}")
def eliminar_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(InventarioItem).filter(InventarioItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/analisis")
async def analisis_cfo(db: Session = Depends(get_db)):
    """Claude analiza el estado del inventario."""
    items = db.query(InventarioItem).all()
    if not items:
        return {"analisis": "No hay items en el inventario. Agrega productos primero."}

    inv_dict = [
        {
            "nombre":         i.nombre,
            "categoria":      i.categoria,
            "unidad":         i.unidad,
            "cantidad":       i.cantidad,
            "costo_unitario": i.costo_unitario,
            "minimo":         i.minimo,
        }
        for i in items
    ]
    analisis = await analizar_inventario(inv_dict)
    return {
        "total_items":       len(items),
        "valor_total":       sum(i.cantidad * i.costo_unitario for i in items),
        "items_bajo_minimo": sum(1 for i in items if i.minimo > 0 and i.cantidad < i.minimo),
        "analisis":          analisis,
    }
