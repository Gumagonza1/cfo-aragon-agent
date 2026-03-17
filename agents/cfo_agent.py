"""
cfo_agent.py – Agente CFO (Claude) para análisis financiero interno.
Analiza: ingresos manuales, gastos, inventario.
NO mezcla con impuestos (esos vienen de CFDIs del SAT).
"""

import os
import json
from datetime import datetime, date

import anthropic

_anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

NEGOCIO = {
    "nombre":    "Tacos Aragón",
    "ciudad":    "Culiacán, Sinaloa",
    "giro":      "Taquería / Restaurante",
    "horario":   "Martes a Domingo, 18:00 - 23:30",
}

PROMPT_CFO = """Eres el CFO (Director Financiero) de Tacos Aragón, una taquería familiar en Culiacán, Sinaloa.
Tu rol es analizar la salud financiera del negocio usando los datos de ingresos, gastos e inventario.

IMPORTANTE: Este análisis es INTERNO del negocio. Los impuestos se calculan por separado con las facturas del SAT.

=== CATALOGO DE CUENTAS CONTABLES ===

INGRESOS (cuentas 4xxx):
  ventas_efectivo      → 4001 Ingresos por Ventas / Efectivo
  ventas_transferencia → 4001 Ingresos por Ventas / Transferencia Bancaria
  ventas_tarjeta       → 4001 Ingresos por Ventas / Tarjeta Bancaria (POS)
  ventas_link          → 4001 Ingresos por Ventas / Link de Pago / Online
  retiro_banco         → 1102 Movimiento Caja: Banco → Efectivo (NO es ingreso real)
  otros_ingresos       → 4900 Ingresos Varios

COSTOS (cuentas 5xxx):
  costo_venta          → 5001 Costo de Ventas / Materia Prima
  empaque              → 5101 Material de Empaque y Desechables

NOMINA Y SEGURIDAD SOCIAL (cuentas 6001-6002):
  nomina               → 6001 Sueldos y Salarios
  imss                 → 6002 Contribuciones Sociales (IMSS, INFONAVIT)

GASTOS FIJOS (cuentas 6101-6202):
  renta                → 6101 Arrendamiento del Local
  luz_gas_agua         → 6201 Servicios Publicos (Luz, Gas, Agua)
  tel_internet         → 6202 Comunicaciones (Telefono, Internet)

GASTOS OPERATIVOS (cuentas 6301-6601):
  mantenimiento        → 6301 Mantenimiento y Reparaciones
  transporte           → 6401 Transportes y Gasolina
  publicidad           → 6501 Publicidad y Marketing
  limpieza             → 6601 Articulos de Limpieza e Higiene

PAGOS A PROVEEDORES (cuentas 6xxx - Compras a credito o contado):
  pago_proveedor_ef    → Pago a Proveedor en Efectivo
  pago_proveedor_tr    → Pago a Proveedor por Transferencia
  pago_proveedor_td    → Pago a Proveedor con Tarjeta de Debito

GASTOS DE ADMINISTRACION (cuentas 7xxx):
  honorarios           → 7001 Honorarios Contables y Legales
  papeleria            → 7101 Papeleria y Utiles de Oficina
  otros_gastos         → 7900 Gastos Varios

MOVIMIENTOS DE CAJA Y CREDITO (cuentas 1xxx-2xxx, NO afectan resultados):
  deposito_banco       → 1102 Deposito: Efectivo → Cuenta Bancaria
  pago_credito         → 2101 Pago de Tarjeta de Credito del Negocio

NOTA IMPORTANTE para el analisis:
- "retiro_banco" y "deposito_banco" son movimientos entre cuentas, NO son ingresos ni gastos reales.
  Excluyelos del Estado de Resultados pero incluyelos en el flujo de caja.
- "pago_credito" es pago de pasivo, NO es gasto operativo.
- Los pagos a proveedores (pago_proveedor_*) SI son gastos operativos del periodo.
- Para ingresos reales de ventas, suma solo ventas_efectivo + ventas_transferencia + ventas_tarjeta + ventas_link.

=== FIN CATALOGO ===

Cuando analices datos financieros proporciona:

ESTADO DE RESULTADOS:
- Ingresos por ventas (desglosados por metodo de cobro: efectivo, transferencia, tarjeta, link)
- Costos de ventas: materia prima + empaque
- Utilidad bruta y margen bruto
- Gastos de operacion por categoria
- Utilidad de operacion
- Gastos de administracion
- Utilidad neta y margen neto

BALANCE GENERAL (simplificado):
- Activos: caja estimada + banco estimado + inventario valorizado
- Pasivos: saldo estimado de creditos
- Capital contable y utilidad acumulada

FLUJO DE CAJA:
- Entradas reales de efectivo (ventas efectivo + retiros banco)
- Salidas de efectivo (gastos pagados en efectivo + depositos banco)
- Posicion de caja estimada

KPIs DEL NEGOCIO:
- Costo de materia prima como % de ventas
- Margen de contribucion
- Punto de equilibrio mensual estimado
- Dias de nomina vs ingresos

RECOMENDACIONES:
- 3-5 acciones concretas y especificas para el negocio

Responde en español con numeros concretos en pesos mexicanos (MXN). Sin emojis.
"""


async def generar_estado_resultados(ingresos: list, gastos: list, periodo: str) -> str:
    """Claude genera el Estado de Resultados del período."""
    total_ingresos = sum(i["monto"] for i in ingresos)
    total_gastos   = sum(g["monto"] for g in gastos)
    utilidad       = total_ingresos - total_gastos

    # Agrupar gastos por tipo
    gastos_por_tipo: dict = {}
    for g in gastos:
        tipo = g.get("tipo", "otros")
        gastos_por_tipo[tipo] = gastos_por_tipo.get(tipo, 0) + g["monto"]

    # Agrupar ingresos por tipo
    ingresos_por_tipo: dict = {}
    for i in ingresos:
        tipo = i.get("tipo", "ventas")
        ingresos_por_tipo[tipo] = ingresos_por_tipo.get(tipo, 0) + i["monto"]

    datos = {
        "periodo":           periodo,
        "ingresos_total":    total_ingresos,
        "ingresos_por_tipo": ingresos_por_tipo,
        "gastos_total":      total_gastos,
        "gastos_por_tipo":   gastos_por_tipo,
        "utilidad_neta":     utilidad,
        "margen_neto":       f"{(utilidad/total_ingresos*100):.1f}%" if total_ingresos > 0 else "N/A",
        "detalle_ingresos":  ingresos[-30:],   # últimos 30
        "detalle_gastos":    gastos[-50:],     # últimos 50
    }

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        system=PROMPT_CFO,
        messages=[{
            "role": "user",
            "content": f"Genera el Estado de Resultados de {NEGOCIO['nombre']} para el período {periodo}:\n\n{json.dumps(datos, ensure_ascii=False, indent=2, default=str)}"
        }],
    )
    return response.content[0].text


async def generar_balance(ingresos: list, gastos: list, inventario: list, periodo: str) -> str:
    """Claude genera el Balance General simplificado."""
    valor_inventario = sum(i["cantidad"] * i["costo_unitario"] for i in inventario)
    utilidades_acum  = sum(i["monto"] for i in ingresos) - sum(g["monto"] for g in gastos)

    datos = {
        "periodo":           periodo,
        "activos": {
            "inventario_valorizado": valor_inventario,
            "items_inventario":      len(inventario),
        },
        "capital": {
            "utilidad_periodo": utilidades_acum,
        },
        "inventario_detalle": inventario[:30],
    }

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=2500,
        system=PROMPT_CFO,
        messages=[{
            "role": "user",
            "content": f"Genera el Balance General simplificado de {NEGOCIO['nombre']} al {periodo}:\n\n{json.dumps(datos, ensure_ascii=False, indent=2, default=str)}"
        }],
    )
    return response.content[0].text


async def analizar_inventario(inventario: list) -> str:
    """Claude analiza el inventario y genera alertas."""
    alertas = [
        i for i in inventario
        if i.get("minimo", 0) > 0 and i.get("cantidad", 0) < i.get("minimo", 0)
    ]
    valor_total = sum(i["cantidad"] * i["costo_unitario"] for i in inventario)

    datos = {
        "total_items":    len(inventario),
        "valor_total":    valor_total,
        "items_bajo_min": len(alertas),
        "alertas":        alertas,
        "inventario":     inventario,
    }

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        system=PROMPT_CFO,
        messages=[{
            "role": "user",
            "content": f"Analiza el inventario de {NEGOCIO['nombre']}:\n\n{json.dumps(datos, ensure_ascii=False, indent=2, default=str)}"
        }],
    )
    return response.content[0].text


async def chat_cfo(pregunta: str, contexto: dict = None) -> str:
    """Chat libre con el CFO."""
    contenido = pregunta
    if contexto:
        contenido = f"[Contexto financiero disponible: {json.dumps(contexto, ensure_ascii=False, default=str)[:2000]}]\n\n{pregunta}"

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=PROMPT_CFO,
        messages=[{"role": "user", "content": contenido}],
    )
    return response.content[0].text
