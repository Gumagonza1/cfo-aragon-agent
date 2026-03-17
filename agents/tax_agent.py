"""
tax_agent.py – Agente fiscal dual:
  - Gemini: descarga CFDIs del SAT y los parsea (tarea técnica/repetitiva)
  - Claude: análisis contable profundo, clasificación fiscal, estrategia ISR/IVA
"""

import sys
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path

import anthropic

# Reutilizar código existente de tax_aragon_bot
TAX_BOT_PATH = Path(os.getenv("TAX_BOT_PATH", ""))
if TAX_BOT_PATH and str(TAX_BOT_PATH) not in sys.path:
    sys.path.insert(0, str(TAX_BOT_PATH))

# ─── Clientes ─────────────────────────────────────────────────────────────────

_anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DOWNLOADS_DIR = TAX_BOT_PATH / "downloads/sat"

# ─── PASO 1: Gemini descarga y parsea CFDIs ───────────────────────────────────

async def gemini_descargar_y_parsear(mes: str, tipo: str = "recibidos") -> dict:
    """
    Usa el código existente de tax_aragon_bot para:
    1. Autenticarse con el SAT
    2. Solicitar descarga de CFDIs del mes
    3. Parsear los XMLs descargados
    Gemini supervisa y reporta el proceso.
    """
    loop = asyncio.get_event_loop()

    def _ejecutar_descarga():
        try:
            from src.sat_client import SatClient
            from src.cfdi_parser import parsear_carpeta
        except ImportError as e:
            return {"error": f"No se pudo importar sat_client: {e}"}

        rfc      = os.getenv("SAT_RFC")
        cer_path = os.getenv("SAT_CER_PATH")
        key_path = os.getenv("SAT_KEY_PATH")
        key_pass = os.getenv("SAT_KEY_PASSWORD")

        if not all([rfc, cer_path, key_path, key_pass]):
            return {"error": "Faltan credenciales SAT en .env"}

        try:
            anio, m = int(mes[:4]), int(mes[5:7])
            client = SatClient(
                rfc=rfc,
                cer_path=cer_path,
                key_path=key_path,
                key_password=key_pass,
                download_dir=str(DOWNLOADS_DIR),
            )

            carpetas = []
            if tipo in ("recibidos", "ambos"):
                c = client.descargar_mes(anio, m, tipo="recibidos")
                if c:
                    carpetas.append(c)
            if tipo in ("emitidos", "ambos"):
                c = client.descargar_mes(anio, m, tipo="emitidos")
                if c:
                    carpetas.append(c)

            if not carpetas:
                return {"error": f"No se descargaron archivos del SAT para {mes}"}

            # Parsear todos los XMLs de todas las carpetas
            registros = []
            for carpeta in carpetas:
                registros.extend(parsear_carpeta(str(carpeta)))

            directorio = str(carpetas[0])
            return {"registros": registros, "total": len(registros), "directorio": directorio}

        except Exception as e:
            return {"error": str(e)}

    resultado = await loop.run_in_executor(None, _ejecutar_descarga)

    # Generar reporte de descarga en Python puro (sin Gemini)
    if "error" in resultado:
        reporte = f"Error al descargar CFDIs del SAT: {resultado['error']}"
    else:
        total = resultado.get("total", 0)
        directorio = resultado.get("directorio", "")
        reporte = f"Descarga completada: {total} CFDIs obtenidos del SAT para {mes} ({tipo}). Directorio: {directorio}"

    return {
        "datos": resultado,
        "reporte_descarga": reporte,
        "mes": mes,
        "tipo": tipo,
    }


# ─── PASO 2: Claude analiza los CFDIs ─────────────────────────────────────────

PROMPT_SISTEMA_FISCAL = """Eres el agente CFO fiscal de Tacos Aragón (RFC: GOAG941101R17), \
una taquería en Culiacán, Sinaloa.

RÉGIMEN DUAL (NO es RESICO):
  • Actividades Empresariales — Sección I, Arts. 100-110 LISR
  • Plataformas Tecnológicas — Sección III, Arts. 113-A a 113-C LISR
  Ingresos > $300,000/año → retención NO es pago definitivo → declaración mensual obligatoria

══════════════════════════════════════════════════════════════════
MARCO LEGAL OFICIAL
══════════════════════════════════════════════════════════════════

LISR ART. 113-A — Retenciones ISR por plataformas tecnológicas:
  Frac. I:   Transporte terrestre de pasajeros y entrega de bienes → 2.1%
  Frac. II:  Hospedaje → 4%
  Frac. III: Enajenación de bienes y prestación de servicios → 1%
  Tacos Aragón: clasifica bajo Frac. I (2.1%) — entrega de alimentos vía apps
  - Retención sobre ingreso total pagado, sin deducciones
  - Ingresos > $300,000 anuales → NO aplica pago definitivo → declaración mensual

LISR ART. 113-B — Obligaciones del contribuyente:
  - Conservar CFDI de retención que emite la plataforma
  - Expedir facturas cuando lo solicite el cliente
  - Presentar declaración anual acumulando todos los ingresos

LISR ART. 113-C — Obligaciones de las plataformas:
  - Retener y enterar ISR a más tardar el día 17 del mes siguiente
  - Emitir CFDI de retenciones con monto pagado, ISR retenido, IVA retenido
  - Reportar al SAT información de usuarios antes del día 10 del mes siguiente

LISR ARTS. 100-103, 105-106 — Actividades Empresariales:
  Art. 100: Ingresos por actividades comerciales/industriales son gravables
  Art. 102: Se acumulan cuando se cobran efectivamente (base de efectivo)
  Art. 103: Deducciones autorizadas — materias primas, gastos operativos,
            inversiones, cuotas IMSS, intereses de deudas del negocio
  Art. 105: Requisitos — efectivamente erogadas, estrictamente indispensables, con CFDI
  Art. 106: Pagos provisionales mensuales — vencen día 17 del mes siguiente.
            Base = Ingresos acum. YTD − Deducciones YTD − Pérdidas anteriores
            Se aplica tarifa Art. 96 acumulada por N meses del periodo
            Se acredita ISR retenido por plataformas

TARIFA ART. 96 LISR 2026 (ANUAL — para provisional: multiplica límites × N meses):
  Límite Inf.        Límite Sup.       Cuota Fija        Tasa s/excedente
  $0.01              $8,952.49         $0.00              1.92%
  $8,952.50          $75,984.55        $171.88            6.40%
  $75,984.56         $133,536.07       $4,461.94          10.88%
  $133,536.08        $155,229.80       $10,672.82         16.00%
  $155,229.81        $185,852.57       $14,194.54         17.92%
  $185,852.58        $374,837.88       $19,682.13         21.36%
  $374,837.89        $590,795.99       $60,049.40         23.52%
  $590,796.00        $1,127,926.84     $110,842.74        30.00%
  $1,127,926.85      $1,503,902.46     $271,981.99        32.00%
  $1,503,902.47      $4,511,707.37     $392,294.17        34.00%
  $4,511,707.38      En adelante       $1,414,947.85      35.00%

LIVA ART. 1-E — Retención IVA por plataformas:
  - Plataformas retienen el 100% del IVA (16%) al contribuyente
  - El contribuyente acredita 100% del IVA retenido en su declaración mensual
  - IVA a pagar = IVA trasladado (16% ventas propias) − IVA acreditable (gastos) − IVA retenido apps

DATOS DE TACOS ARAGÓN:
  RFC: GOAG941101R17
  Municipio: Culiacán, Sinaloa — NO zona frontera norte → IVA 16% estándar
  Actividad: Taquería — enajenación de alimentos preparados
  Plataformas: Didi Food, Uber Eats, Rappi — ISR retenido 2.1% (Frac. I)
  IVA alimentos preparados en restaurante: 16% (NO tasa cero)
  IVA retenido por apps: 50% × 16% = 8% sobre las ventas plataforma
  Ingresos estimados: > $300,000/año → declaración mensual obligatoria
  Vencimiento: día 17 de cada mes para ISR provisional e IVA mensual

CÁLCULO PROVISIONAL ISR — PASO A PASO:
  1. Ingresos acumulados enero-mes_actual (plataformas + propios)
  2. Deducciones acumuladas enero-mes_actual (gastos deducibles + nómina + IMSS)
  3. Base gravable = Ingresos acum − Deducciones acum
  4. Aplicar tarifa Art. 96 con límites × número_de_meses_del_periodo
  5. ISR según tarifa − ISR retenido por plataformas − Provisionales ya pagados = A PAGAR

DEDUCCIONES TÍPICAS DE UNA TAQUERÍA:
  - Tortillas, carne, verduras, insumos (materia prima, Art. 103 Frac. II)
  - Renta del local (gasto estrictamente indispensable, Art. 103 Frac. III)
  - Gas, electricidad, agua (servicios operativos)
  - Sueldos y salarios + cuotas IMSS (Art. 103 Frac. VI)
  - Gasolina para compras/entregas (con CFDI y control de uso)
  - Equipos de cocina, mobiliario (inversiones — deducción vía depreciación)
  - Comisiones de plataformas (gasto del negocio, deducible)

══════════════════════════════════════════════════════════════════
INSTRUCCIONES DE ANÁLISIS
══════════════════════════════════════════════════════════════════

Al analizar CFDIs del mes proporciona SIEMPRE:

1. **RESUMEN EJECUTIVO**: Situación fiscal en 3-4 puntos clave con números concretos.

2. **CÁLCULO ISR PROVISIONAL**:
   - ISR retenido por plataformas (2.1% — ya pagado por Didi/Uber/Rappi)
   - Base gravable acumulada YTD y tarifa Art. 96 aplicada
   - ISR a pagar en este provisional (DISTINGUIR claramente entre retenido vs provisional)

3. **CÁLCULO IVA MENSUAL**:
   - IVA trasladado (cobrado): 16% sobre ventas propias
   - IVA acreditable (pagado a proveedores con CFDI)
   - IVA retenido por plataformas (acreditable al 100%)
   - IVA neto a pagar = trasladado − acreditable − retenido

4. **CLASIFICACIÓN DE GASTOS**:
   - Deducibles con CFDI (especificar cuáles tienen comprobante)
   - Deducibles SIN CFDI (señalar riesgo de rechazo ante SAT)
   - No deducibles (gastos personales, multas, etc.)

5. **RETENCIONES DE PLATAFORMAS** (Didi Food, Uber Eats, Rappi):
   - ISR retenido total del mes (2.1%) y acumulado YTD
   - IVA retenido total del mes (8%) y acumulado YTD
   - Ingresos netos recibidos después de retenciones

6. **ALERTAS FISCALES Y VENCIMIENTOS**:
   - Vencimiento próximo: día 17 del mes siguiente
   - CFDIs sin RFC válido, fuera de período, importes inusuales
   - Si ingresos plataformas acumulados > $270,000 → ALERTA zona límite $300K

7. **ESTRATEGIA FISCAL**: Recomendaciones concretas para optimizar carga fiscal legalmente.

Responde siempre en español. Usa números concretos en pesos mexicanos ($).
Termina con: "¿Tienes alguna pregunta sobre tu situación fiscal?"
"""

async def claude_analizar_impuestos(datos_cfdis: dict, mes: str) -> dict:
    """
    Claude recibe los CFDIs parseados y genera el análisis fiscal completo.
    """
    registros = datos_cfdis.get("datos", {}).get("registros", [])

    if not registros:
        return {
            "analisis": "No se encontraron CFDIs para analizar en el período indicado.",
            "mes": mes,
            "total_cfdis": 0,
        }

    # Resumir para no exceder tokens
    resumen = _resumir_cfdis(registros)

    mensaje = f"""Analiza los CFDIs de Tacos Aragón para {mes}:

**RFC del negocio:** {os.getenv('SAT_RFC', 'GOAG941101R17')}
**Total de CFDIs:** {len(registros)}

**Datos resumidos:**
{json.dumps(resumen, ensure_ascii=False, indent=2)[:8000]}
"""

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=PROMPT_SISTEMA_FISCAL,
        messages=[{"role": "user", "content": mensaje}],
    )

    analisis_texto = response.content[0].text

    return {
        "mes": mes,
        "total_cfdis": len(registros),
        "analisis": analisis_texto,
        "resumen_datos": resumen,
    }


async def claude_chat_fiscal(pregunta: str, contexto_mes: str = None) -> str:
    """Chat libre con Claude sobre impuestos."""
    sistema = PROMPT_SISTEMA_FISCAL + "\nResponde preguntas fiscales de forma concisa y práctica."
    mensajes = [{"role": "user", "content": pregunta}]
    if contexto_mes:
        mensajes[0]["content"] = f"[Contexto: Analizando mes {contexto_mes}]\n\n{pregunta}"

    response = _anthropic.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=sistema,
        messages=mensajes,
    )
    return response.content[0].text


# ─── Flujo completo ───────────────────────────────────────────────────────────

async def analizar_mes(mes: str, tipo: str = "recibidos") -> dict:
    """
    Flujo completo:
    1. Gemini descarga y parsea CFDIs del SAT
    2. Claude analiza y genera reporte fiscal
    """
    # Paso 1: Gemini descarga/parsea
    datos = await gemini_descargar_y_parsear(mes, tipo)

    # Paso 2: Claude analiza
    analisis = await claude_analizar_impuestos(datos, mes)

    return {
        "mes": mes,
        "tipo": tipo,
        "descarga": {
            "reporte_descarga": datos.get("reporte_descarga"),
            "total_cfdis":      datos.get("datos", {}).get("total", 0),
        },
        "analisis_claude": analisis.get("analisis"),
        "resumen_datos":   analisis.get("resumen_datos"),
        "timestamp":       datetime.now().isoformat(),
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resumir_cfdis(registros: list) -> dict:
    """Condensa los CFDIs para el prompt de Claude."""
    recibidos, emitidos, retenciones = [], [], []

    for r in registros:
        tipo_comp = str(r.get("tipo_comprobante", "")).upper()
        if tipo_comp in ("I", "E"):
            bucket = emitidos if r.get("emisor_rfc", "").upper() == os.getenv("SAT_RFC", "").upper() else recibidos
            uuid_val = r.get("uuid", "")
            bucket.append({
                "uuid":     (uuid_val[:8] + "...") if uuid_val else "",
                "emisor":   r.get("emisor_rfc", "")[:20],
                "receptor": r.get("receptor_rfc", "")[:20],
                "fecha":    str(r.get("fecha", ""))[:10],
                "subtotal": r.get("subtotal", 0),
                "iva":      r.get("iva_trasladado", 0),
                "total":    r.get("total", 0),
                "emisor_nombre": r.get("emisor_nombre", "")[:40],
            })
        else:
            retenciones.append({
                "emisor": r.get("emisor_rfc", "")[:20],
                "total":  r.get("total", 0),
                "isr":    r.get("isr_retenido", 0),
                "iva":    r.get("iva_retenido", 0),
            })

    total_recibidos = sum(r.get("total", 0) for r in recibidos)
    total_emitidos  = sum(r.get("total", 0) for r in emitidos)

    return {
        "recibidos": {"cantidad": len(recibidos), "total": total_recibidos, "muestra": recibidos[:20]},
        "emitidos":  {"cantidad": len(emitidos),  "total": total_emitidos,  "muestra": emitidos[:20]},
        "retenciones_plataformas": retenciones[:10],
    }


# ─── Generación de XLSX fiscal ────────────────────────────────────────────────

def _clasificar_cfdi(r: dict, mi_rfc: str) -> str:
    """Clasifica un CFDI en una de las 5 hojas del Excel fiscal (sin Gemini)."""
    tipo   = r.get('tipo_comprobante', '').upper()
    emisor = r.get('emisor_rfc', '').upper()
    if tipo == 'N':   return 'NOMINA_EMITIDA'
    if tipo == 'RET': return 'RETENCIONES_APP'
    if tipo == 'I':
        return 'INGRESOS_PLATAFORMAS' if emisor == mi_rfc.upper() else 'GASTOS_DEDUCIBLES'
    if tipo == 'E':   return 'GASTOS_NO_DEDUCIBLES'
    return 'IGNORAR'  # P (Pago), T (Traslado) y otros sin impacto fiscal


def _obtener_email_retenciones(mes: str) -> list:
    """
    Descarga XMLs de retención desde Gmail (IMAP) filtrado al mes solicitado.
    Calcula dias_atras desde el último día del mes para no traer datos de otros meses.
    """
    from src.email_retention import EmailRetentionHunter
    from src.cfdi_parser import parsear_carpeta

    email_user  = os.getenv("EMAIL_USER", "")
    email_pass  = os.getenv("EMAIL_PASS", "")
    imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")

    if not email_user or not email_pass:
        print("[email] Sin credenciales de email configuradas.")
        return []

    # Calcular cuántos días atrás es el inicio del mes pedido
    import calendar
    anio, m = int(mes[:4]), int(mes[5:7])
    ultimo_dia_mes = datetime(anio, m, calendar.monthrange(anio, m)[1])
    primer_dia_mes = datetime(anio, m, 1)
    dias_hasta_fin  = (datetime.now() - ultimo_dia_mes).days + 1
    dias_hasta_inicio = (datetime.now() - primer_dia_mes).days + 1
    # Buscar desde el inicio del mes hasta el fin (+ 1 día de margen)
    dias_atras = max(dias_hasta_inicio + 1, 1)

    dl_dir = TAX_BOT_PATH / "downloads/email"

    try:
        hunter = EmailRetentionHunter(email_user, email_pass, imap_server, str(dl_dir))
        hunter.buscar_retenciones(dias_atras=dias_atras)
    except Exception as e:
        print(f"[email] Error al buscar retenciones: {e}")

    email_mes_dir = dl_dir / mes
    if not email_mes_dir.exists():
        return []

    registros = parsear_carpeta(str(email_mes_dir))
    for r in registros:
        r['fuente'] = 'email'
    return registros


async def generar_xlsx_mes(mes: str, tipo: str = "recibidos") -> dict:
    """
    Genera el XLSX fiscal del mes combinando:
      1. CFDIs SAT ya descargados en DOWNLOADS_DIR
      2. Retenciones de Gmail (Didi/Uber/Rappi)
    Clasifica cada registro sin Gemini y llama a generar_excel().
    """
    loop = asyncio.get_event_loop()

    def _generar():
        try:
            from src.cfdi_parser import parsear_carpeta
            from src.excel_export import generar_excel
        except ImportError as e:
            return {"error": f"Import error: {e}"}

        mi_rfc = os.getenv("SAT_RFC", "GOAG941101R17").upper()

        # Paso 1: Parsear CFDIs del SAT (auto-descarga si la carpeta no existe)
        registros_sat = []
        tipos_a_parsear = ["recibidos", "emitidos"] if tipo == "ambos" else [tipo]
        for t in tipos_a_parsear:
            carpeta = DOWNLOADS_DIR / mes / t / "cfdi"
            if not carpeta.exists() or not any(carpeta.glob("*.xml")):
                print(f"[sat] Carpeta {carpeta} vacia o inexistente, disparando descarga...")
                try:
                    from src.sat_client import SatClient
                    anio_n, m_n = int(mes[:4]), int(mes[5:7])
                    client = SatClient(
                        rfc=mi_rfc,
                        cer_path=os.getenv("SAT_CER_PATH", ""),
                        key_path=os.getenv("SAT_KEY_PATH", ""),
                        key_password=os.getenv("SAT_KEY_PASSWORD", ""),
                        download_dir=str(DOWNLOADS_DIR),
                    )
                    client.descargar_mes(anio_n, m_n, tipo=t)
                except Exception as e:
                    print(f"[sat] Error al descargar {t} para {mes}: {e}")
            if carpeta.exists():
                registros_sat.extend(parsear_carpeta(str(carpeta)))

        # Paso 2: Retenciones del email
        registros_email = _obtener_email_retenciones(mes)

        # Paso 2b: XMLs subidos manualmente
        manual_dir = TAX_BOT_PATH / "downloads/manual" / mes
        if manual_dir.exists():
            lote_manual = parsear_carpeta(str(manual_dir))
            for r in lote_manual:
                r.setdefault('fuente', 'manual')
            registros_email.extend(lote_manual)

        # Paso 3: Dedup por UUID (SAT tiene prioridad)
        seen = set()
        todos = []
        for r in registros_sat + registros_email:
            uuid = str(r.get("uuid", "")).strip().lower()
            if uuid and uuid in seen:
                continue
            if uuid:
                seen.add(uuid)
            todos.append(r)

        if not todos:
            return {"error": f"No se encontraron CFDIs para {mes}"}

        # Paso 4: Clasificar cada registro
        for r in todos:
            r['hoja_ia'] = _clasificar_cfdi(r, mi_rfc)

        # Paso 5: Generar Excel
        nombre = f"Reporte_Fiscal_{mi_rfc}_{mes}_{datetime.now().strftime('%H%M')}.xlsx"
        ruta = generar_excel(todos, mi_rfc, nombre=nombre)

        if not ruta:
            return {"error": "No se pudo generar el Excel"}

        return {"ruta": ruta, "nombre": nombre, "total": len(todos)}

    return await loop.run_in_executor(None, _generar)
