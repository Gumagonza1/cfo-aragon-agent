"""
routes/impuestos.py – Endpoints de análisis fiscal (CFDIs del SAT).
"""

import asyncio
import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import AnalisisFiscal, DeclaracionMensual
from agents.tax_agent import analizar_mes, claude_chat_fiscal, generar_xlsx_mes, DOWNLOADS_DIR

router = APIRouter(prefix="/api/impuestos", tags=["impuestos"])


class AnalizarRequest(BaseModel):
    mes:  str   # "2026-03"
    tipo: str = "recibidos"  # "recibidos" | "emitidos" | "ambos"


class ChatRequest(BaseModel):
    pregunta: str
    mes: str = None


@router.post("/analizar")
async def analizar(req: AnalizarRequest, db: Session = Depends(get_db)):
    """Descarga CFDIs del SAT (Gemini) y los analiza (Claude)."""
    # Validar formato mes
    try:
        datetime.strptime(req.mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM (ej. 2026-03)")

    if req.tipo not in ("recibidos", "emitidos", "ambos"):
        raise HTTPException(400, "tipo debe ser: recibidos, emitidos o ambos")

    resultado = await analizar_mes(req.mes, req.tipo)

    # Guardar en DB
    registro = AnalisisFiscal(
        mes=req.mes,
        tipo=req.tipo,
        resultado=json.dumps(resultado, ensure_ascii=False, default=str),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)

    return {**resultado, "id": registro.id}


@router.get("/resultado")
def ultimo_resultado(mes: str = None, db: Session = Depends(get_db)):
    """Devuelve el último análisis fiscal guardado."""
    query = db.query(AnalisisFiscal).order_by(AnalisisFiscal.creado_en.desc())
    if mes:
        query = query.filter(AnalisisFiscal.mes == mes)
    registro = query.first()

    if not registro:
        return {"mensaje": "No hay análisis guardados aún.", "datos": None}

    return {
        "id":         registro.id,
        "mes":        registro.mes,
        "tipo":       registro.tipo,
        "creado_en":  registro.creado_en,
        "resultado":  json.loads(registro.resultado) if registro.resultado else None,
    }


@router.get("/historial")
def historial(db: Session = Depends(get_db)):
    """Lista todos los análisis fiscales guardados."""
    registros = db.query(AnalisisFiscal).order_by(AnalisisFiscal.creado_en.desc()).limit(24).all()
    return [
        {"id": r.id, "mes": r.mes, "tipo": r.tipo, "creado_en": r.creado_en}
        for r in registros
    ]


@router.post("/chat")
async def chat_fiscal(req: ChatRequest):
    """Chat con Claude sobre impuestos."""
    respuesta = await claude_chat_fiscal(req.pregunta, req.mes)
    return {"respuesta": respuesta}


@router.post("/subir-xml")
async def subir_xml(
    mes: str = Form(...),
    archivos: List[UploadFile] = File(...),
):
    """
    Sube XMLs o ZIPs con XMLs para un mes.
    Se guardan en downloads/manual/YYYY-MM/ y se incluyen al generar el Excel.
    """
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes invalido. Usa YYYY-MM (ej. 2026-03)")

    from agents.tax_agent import TAX_BOT_PATH
    base_dir = TAX_BOT_PATH / "downloads/manual" / mes
    base_dir.mkdir(parents=True, exist_ok=True)

    guardados = []
    for archivo in archivos:
        contenido = await archivo.read()
        nombre = archivo.filename or f"archivo_{len(guardados)}.xml"

        if nombre.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
                    for entry in zf.namelist():
                        if entry.lower().endswith(".xml"):
                            xml_nombre = Path(entry).name
                            (base_dir / xml_nombre).write_bytes(zf.read(entry))
                            guardados.append(xml_nombre)
            except zipfile.BadZipFile:
                raise HTTPException(400, f"ZIP invalido: {nombre}")

        elif nombre.lower().endswith(".xml"):
            (base_dir / nombre).write_bytes(contenido)
            guardados.append(nombre)

        else:
            raise HTTPException(400, f"Solo se aceptan .xml y .zip (recibido: {nombre})")

    return {"mes": mes, "guardados": guardados, "total": len(guardados)}


@router.get("/manuales/{mes}")
def listar_manuales(mes: str):
    """Lista los XMLs subidos manualmente para un mes."""
    from agents.tax_agent import TAX_BOT_PATH
    directorio = TAX_BOT_PATH / "downloads/manual" / mes
    if not directorio.exists():
        return {"mes": mes, "archivos": [], "total": 0}
    archivos = [f.name for f in sorted(directorio.iterdir()) if f.suffix.lower() == ".xml"]
    return {"mes": mes, "archivos": archivos, "total": len(archivos)}


@router.delete("/manuales/{mes}/{filename}")
def eliminar_manual(mes: str, filename: str):
    """Elimina un XML subido manualmente."""
    import re
    if not re.match(r'^[\w\-\.]+\.xml$', filename):
        raise HTTPException(400, "Nombre invalido")
    from agents.tax_agent import TAX_BOT_PATH
    ruta = TAX_BOT_PATH / "downloads/manual" / mes / filename
    if not ruta.exists():
        raise HTTPException(404, "Archivo no encontrado")
    ruta.unlink()
    return {"eliminado": filename}


@router.post("/exportar-xlsx")
async def exportar_xlsx(req: AnalizarRequest):
    """Genera el XLSX fiscal del mes con CFDIs del SAT + retenciones de Gmail."""
    try:
        datetime.strptime(req.mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM (ej. 2026-03)")

    if req.tipo not in ("recibidos", "emitidos", "ambos"):
        raise HTTPException(400, "tipo debe ser: recibidos, emitidos o ambos")

    resultado = await generar_xlsx_mes(req.mes, req.tipo)
    if "error" in resultado:
        raise HTTPException(400, resultado["error"])

    return {
        "nombre":       resultado["nombre"],
        "url_descarga": f"/api/impuestos/descargar/{resultado['nombre']}",
        "total_cfdis":  resultado["total"],
    }


@router.get("/descargar/{filename}")
def descargar_xlsx(filename: str):
    """Descarga el archivo XLSX generado por /exportar-xlsx."""
    import re
    from fastapi.responses import FileResponse
    from pathlib import Path

    if not re.match(r'^[\w\-\.]+\.xlsx$', filename):
        raise HTTPException(400, "Nombre de archivo inválido")

    ruta = Path("output") / filename
    if not ruta.exists():
        raise HTTPException(404, "Archivo no encontrado")

    return FileResponse(
        str(ruta),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── Nuevos endpoints: Declaraciones mensuales ────────────────────────────────

class DeclaracionRequest(BaseModel):
    mes: str                          # "2026-02"
    ingresos_plataformas: float = 0.0
    ingresos_propios: float = 0.0
    gastos_deducibles: float = 0.0
    nomina: float = 0.0
    isr_retenido: float = 0.0
    iva_retenido: float = 0.0
    base_gravable_isr: Optional[float] = None
    isr_tarifa: Optional[float] = None
    isr_provisionales_previos: float = 0.0
    isr_a_pagar: Optional[float] = None
    iva_trasladado: float = 0.0
    iva_acreditable: float = 0.0
    iva_a_pagar: Optional[float] = None
    notas: str = ""


class PagoRequest(BaseModel):
    tipo: str          # "isr" | "iva"
    fecha_pago: str    # "2026-03-17"
    num_operacion: str


def _calcular_isr_tarifa(base: float) -> float:
    """Aplica tarifa Art. 96 LISR 2026 (base anual)."""
    tabla = [
        (0.01,        8_952.49,      0.00,         0.0192),
        (8_952.50,    75_984.55,     171.88,        0.0640),
        (75_984.56,   133_536.07,    4_461.94,      0.1088),
        (133_536.08,  155_229.80,    10_672.82,     0.1600),
        (155_229.81,  185_852.57,    14_194.54,     0.1792),
        (185_852.58,  374_837.88,    19_682.13,     0.2136),
        (374_837.89,  590_795.99,    60_049.40,     0.2352),
        (590_796.00,  1_127_926.84,  110_842.74,    0.3000),
        (1_127_926.85,1_503_902.46,  271_981.99,    0.3200),
        (1_503_902.47,4_511_707.37,  392_294.17,    0.3400),
        (4_511_707.38, float('inf'), 1_414_947.85,  0.3500),
    ]
    if base <= 0:
        return 0.0
    for li, ls, cuota, tasa in tabla:
        if li <= base <= ls:
            return round(cuota + (base - li) * tasa, 2)
    return 0.0


@router.post("/declaracion")
def guardar_declaracion(req: DeclaracionRequest, db: Session = Depends(get_db)):
    """Crea o actualiza la declaración del mes (upsert por mes)."""
    try:
        datetime.strptime(req.mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM (ej. 2026-02)")

    anio = int(req.mes[:4])

    # Calcular base gravable si no viene
    base_gravable = req.base_gravable_isr
    if base_gravable is None:
        base_gravable = max(
            (req.ingresos_plataformas + req.ingresos_propios)
            - (req.gastos_deducibles + req.nomina),
            0.0,
        )

    # Calcular ISR según tarifa si no viene
    isr_tarifa = req.isr_tarifa
    if isr_tarifa is None:
        isr_tarifa = _calcular_isr_tarifa(base_gravable)

    # Calcular ISR a pagar si no viene
    isr_a_pagar = req.isr_a_pagar
    if isr_a_pagar is None:
        isr_a_pagar = max(
            isr_tarifa - req.isr_retenido - req.isr_provisionales_previos,
            0.0,
        )

    # Calcular IVA a pagar si no viene
    iva_a_pagar = req.iva_a_pagar
    if iva_a_pagar is None:
        iva_a_pagar = req.iva_trasladado - req.iva_acreditable - req.iva_retenido

    existing = db.query(DeclaracionMensual).filter(DeclaracionMensual.mes == req.mes).first()

    if existing:
        existing.anio                    = anio
        existing.ingresos_plataformas    = req.ingresos_plataformas
        existing.ingresos_propios        = req.ingresos_propios
        existing.gastos_deducibles       = req.gastos_deducibles
        existing.nomina                  = req.nomina
        existing.isr_retenido            = req.isr_retenido
        existing.iva_retenido            = req.iva_retenido
        existing.base_gravable_isr       = base_gravable
        existing.isr_tarifa              = isr_tarifa
        existing.isr_provisionales_previos = req.isr_provisionales_previos
        existing.isr_a_pagar             = isr_a_pagar
        existing.iva_trasladado          = req.iva_trasladado
        existing.iva_acreditable         = req.iva_acreditable
        existing.iva_a_pagar             = iva_a_pagar
        existing.notas                   = req.notas
        db.commit()
        db.refresh(existing)
        decl = existing
    else:
        decl = DeclaracionMensual(
            mes=req.mes,
            anio=anio,
            ingresos_plataformas=req.ingresos_plataformas,
            ingresos_propios=req.ingresos_propios,
            gastos_deducibles=req.gastos_deducibles,
            nomina=req.nomina,
            isr_retenido=req.isr_retenido,
            iva_retenido=req.iva_retenido,
            base_gravable_isr=base_gravable,
            isr_tarifa=isr_tarifa,
            isr_provisionales_previos=req.isr_provisionales_previos,
            isr_a_pagar=isr_a_pagar,
            iva_trasladado=req.iva_trasladado,
            iva_acreditable=req.iva_acreditable,
            iva_a_pagar=iva_a_pagar,
            notas=req.notas,
        )
        db.add(decl)
        db.commit()
        db.refresh(decl)

    return {
        "mes": decl.mes,
        "anio": decl.anio,
        "ingresos_plataformas": decl.ingresos_plataformas,
        "ingresos_propios": decl.ingresos_propios,
        "base_gravable_isr": decl.base_gravable_isr,
        "isr_tarifa": decl.isr_tarifa,
        "isr_retenido": decl.isr_retenido,
        "isr_provisionales_previos": decl.isr_provisionales_previos,
        "isr_a_pagar": decl.isr_a_pagar,
        "iva_trasladado": decl.iva_trasladado,
        "iva_acreditable": decl.iva_acreditable,
        "iva_retenido": decl.iva_retenido,
        "iva_a_pagar": decl.iva_a_pagar,
        "estado_isr": decl.estado_isr,
        "estado_iva": decl.estado_iva,
        "notas": decl.notas,
    }


@router.get("/declaracion/{mes}")
def obtener_declaracion(mes: str, db: Session = Depends(get_db)):
    """Devuelve la declaración del mes o 404."""
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM")

    decl = db.query(DeclaracionMensual).filter(DeclaracionMensual.mes == mes).first()
    if not decl:
        raise HTTPException(404, f"No hay declaración registrada para {mes}")

    return {
        "id": decl.id,
        "mes": decl.mes,
        "anio": decl.anio,
        "ingresos_plataformas": decl.ingresos_plataformas,
        "ingresos_propios": decl.ingresos_propios,
        "gastos_deducibles": decl.gastos_deducibles,
        "nomina": decl.nomina,
        "isr_retenido": decl.isr_retenido,
        "iva_retenido": decl.iva_retenido,
        "base_gravable_isr": decl.base_gravable_isr,
        "isr_tarifa": decl.isr_tarifa,
        "isr_provisionales_previos": decl.isr_provisionales_previos,
        "isr_a_pagar": decl.isr_a_pagar,
        "iva_trasladado": decl.iva_trasladado,
        "iva_acreditable": decl.iva_acreditable,
        "iva_a_pagar": decl.iva_a_pagar,
        "estado_isr": decl.estado_isr,
        "fecha_pago_isr": decl.fecha_pago_isr,
        "num_operacion_isr": decl.num_operacion_isr,
        "estado_iva": decl.estado_iva,
        "fecha_pago_iva": decl.fecha_pago_iva,
        "num_operacion_iva": decl.num_operacion_iva,
        "notas": decl.notas,
        "creado_en": decl.creado_en,
        "actualizado_en": decl.actualizado_en,
    }


@router.get("/declaraciones/{anio}")
def listar_declaraciones_anio(anio: int, db: Session = Depends(get_db)):
    """Lista todas las declaraciones del año con totales anuales."""
    declaraciones = (
        db.query(DeclaracionMensual)
        .filter(DeclaracionMensual.anio == anio)
        .order_by(DeclaracionMensual.mes)
        .all()
    )

    meses_data = []
    for d in declaraciones:
        meses_data.append({
            "mes": d.mes,
            "ingresos_plataformas": d.ingresos_plataformas,
            "ingresos_propios": d.ingresos_propios,
            "isr_a_pagar": d.isr_a_pagar,
            "iva_a_pagar": d.iva_a_pagar,
            "isr_retenido": d.isr_retenido,
            "iva_retenido": d.iva_retenido,
            "estado_isr": d.estado_isr,
            "estado_iva": d.estado_iva,
            "fecha_pago_isr": d.fecha_pago_isr,
            "fecha_pago_iva": d.fecha_pago_iva,
        })

    totales = {
        "ingresos_plataformas": sum(d.ingresos_plataformas for d in declaraciones),
        "ingresos_propios": sum(d.ingresos_propios for d in declaraciones),
        "isr_pagado": sum(d.isr_a_pagar for d in declaraciones if d.estado_isr == "pagado"),
        "iva_pagado": sum(d.iva_a_pagar for d in declaraciones if d.estado_iva == "pagado"),
        "isr_retenido_total": sum(d.isr_retenido for d in declaraciones),
    }

    return {
        "anio": anio,
        "meses": meses_data,
        "totales": totales,
    }


@router.patch("/declaracion/{mes}/pagar")
def marcar_pagado(mes: str, req: PagoRequest, db: Session = Depends(get_db)):
    """Marca ISR o IVA del mes como pagado."""
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM")

    if req.tipo not in ("isr", "iva"):
        raise HTTPException(400, "tipo debe ser 'isr' o 'iva'")

    decl = db.query(DeclaracionMensual).filter(DeclaracionMensual.mes == mes).first()
    if not decl:
        raise HTTPException(404, f"No hay declaración registrada para {mes}")

    if req.tipo == "isr":
        decl.estado_isr       = "pagado"
        decl.fecha_pago_isr   = req.fecha_pago
        decl.num_operacion_isr = req.num_operacion
    else:
        decl.estado_iva       = "pagado"
        decl.fecha_pago_iva   = req.fecha_pago
        decl.num_operacion_iva = req.num_operacion

    db.commit()
    db.refresh(decl)

    return {
        "mes": decl.mes,
        "estado_isr": decl.estado_isr,
        "estado_iva": decl.estado_iva,
        "fecha_pago_isr": decl.fecha_pago_isr,
        "num_operacion_isr": decl.num_operacion_isr,
        "fecha_pago_iva": decl.fecha_pago_iva,
        "num_operacion_iva": decl.num_operacion_iva,
    }


@router.get("/vencimientos")
def obtener_vencimientos(db: Session = Depends(get_db)):
    """Próximos 3 meses con su estado de declaración y urgencia."""
    hoy = date.today()
    resultado = []

    for i in range(3):
        # mes i: mes actual, mes actual +1, mes actual +2
        if hoy.month + i <= 12:
            anio_mes = hoy.year
            num_mes  = hoy.month + i
        else:
            anio_mes = hoy.year + 1
            num_mes  = (hoy.month + i) - 12

        mes_str = f"{anio_mes:04d}-{num_mes:02d}"

        # Vencimiento: día 17 del mes siguiente
        if num_mes == 12:
            venc_anio = anio_mes + 1
            venc_mes  = 1
        else:
            venc_anio = anio_mes
            venc_mes  = num_mes + 1
        fecha_venc = date(venc_anio, venc_mes, 17)
        dias_rest  = (fecha_venc - hoy).days

        decl = db.query(DeclaracionMensual).filter(DeclaracionMensual.mes == mes_str).first()
        estado_isr = decl.estado_isr if decl else "sin_datos"
        estado_iva = decl.estado_iva if decl else "sin_datos"

        urgente = (
            dias_rest < 5
            and (estado_isr == "pendiente" or estado_iva == "pendiente")
        )

        resultado.append({
            "mes": mes_str,
            "fecha_vencimiento": fecha_venc.isoformat(),
            "estado_isr": estado_isr,
            "estado_iva": estado_iva,
            "dias_restantes": dias_rest,
            "urgente": urgente,
            "isr_a_pagar": decl.isr_a_pagar if decl else None,
            "iva_a_pagar": decl.iva_a_pagar if decl else None,
        })

    return resultado


@router.get("/anual/{anio}")
def resumen_anual(anio: int, db: Session = Depends(get_db)):
    """Resumen anual con proyección y alerta límite $300,000."""
    declaraciones = (
        db.query(DeclaracionMensual)
        .filter(DeclaracionMensual.anio == anio)
        .order_by(DeclaracionMensual.mes)
        .all()
    )

    ingresos_plataformas = sum(d.ingresos_plataformas for d in declaraciones)
    ingresos_propios     = sum(d.ingresos_propios for d in declaraciones)
    isr_pagado           = sum(d.isr_a_pagar for d in declaraciones if d.estado_isr == "pagado")
    iva_pagado           = sum(d.iva_a_pagar for d in declaraciones if d.estado_iva == "pagado")
    isr_retenido_total   = sum(d.isr_retenido for d in declaraciones)

    meses_con_datos = len(declaraciones)
    promedio_mensual = (ingresos_plataformas / meses_con_datos) if meses_con_datos > 0 else 0.0
    proyeccion_anual = promedio_mensual * 12

    meses_pendientes_pago = [
        d.mes for d in declaraciones
        if d.estado_isr == "pendiente" or d.estado_iva == "pendiente"
    ]

    return {
        "anio": anio,
        "ingresos_plataformas": round(ingresos_plataformas, 2),
        "ingresos_propios": round(ingresos_propios, 2),
        "isr_pagado": round(isr_pagado, 2),
        "iva_pagado": round(iva_pagado, 2),
        "isr_retenido_total": round(isr_retenido_total, 2),
        "porcentaje_limite_300k": round((ingresos_plataformas / 300_000) * 100, 1),
        "proyeccion_anual": round(proyeccion_anual, 2),
        "alerta_limite": proyeccion_anual > 270_000,
        "meses_con_datos": meses_con_datos,
        "meses_pendientes_pago": meses_pendientes_pago,
    }


@router.get("/gastos-recurrentes/{mes}")
async def gastos_recurrentes(mes: str):
    """
    Detecta proveedores recurrentes (≥3 apariciones en 4 meses) que no tienen
    CFDI en el mes solicitado.
    """
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Formato de mes inválido. Usa YYYY-MM")

    loop = asyncio.get_event_loop()

    def _analizar():
        try:
            import sys
            from pathlib import Path as P
            import os as _os
            TAX_BOT_PATH = P(_os.getenv("TAX_BOT_PATH", ""))
            if TAX_BOT_PATH and str(TAX_BOT_PATH) not in sys.path:
                sys.path.insert(0, str(TAX_BOT_PATH))
            from src.cfdi_parser import parsear_carpeta
        except ImportError as e:
            return {"error": f"No se pudo importar cfdi_parser: {e}"}

        anio_n = int(mes[:4])
        mes_n  = int(mes[5:7])

        # Generar los 4 meses: mes solicitado y los 3 anteriores
        meses_ventana = []
        for delta in range(4):
            m = mes_n - delta
            a = anio_n
            if m <= 0:
                m += 12
                a -= 1
            meses_ventana.append(f"{a:04d}-{m:02d}")

        # Recolectar CFDIs de cada mes
        proveedores_por_mes = defaultdict(set)  # rfc -> set de meses donde aparece

        for m_str in meses_ventana:
            for tipo in ("recibidos",):
                carpeta = DOWNLOADS_DIR / m_str / tipo / "cfdi"
                if not carpeta.exists():
                    continue
                registros = parsear_carpeta(str(carpeta))
                for r in registros:
                    rfc    = str(r.get("emisor_rfc", "")).strip().upper()
                    nombre = str(r.get("emisor_nombre", "")).strip()
                    if rfc:
                        proveedores_por_mes[rfc].add((m_str, nombre, float(r.get("total", 0))))

        # Calcular estadísticas por proveedor
        stats = {}  # rfc -> {nombre, meses_visto, montos}
        for rfc, apariciones in proveedores_por_mes.items():
            nombres   = [a[1] for a in apariciones]
            nombre    = max(set(nombres), key=nombres.count) if nombres else ""
            meses_vis = set(a[0] for a in apariciones)
            montos    = [a[2] for a in apariciones]
            stats[rfc] = {
                "rfc": rfc,
                "nombre": nombre,
                "meses_visto": len(meses_vis),
                "monto_promedio": round(sum(montos) / len(montos), 2) if montos else 0,
                "presente_este_mes": mes in meses_vis,
            }

        # Filtrar recurrentes (≥ 3 apariciones) que NO tienen CFDI este mes
        recurrentes = [
            v for v in stats.values()
            if v["meses_visto"] >= 3 and not v["presente_este_mes"]
        ]

        recurrentes.sort(key=lambda x: x["monto_promedio"], reverse=True)
        return recurrentes

    resultado = await loop.run_in_executor(None, _analizar)

    if isinstance(resultado, dict) and "error" in resultado:
        raise HTTPException(500, resultado["error"])

    return resultado
