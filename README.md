# CFO Aragón Agent

Servidor FastAPI en el puerto **3002** que actúa como CFO (Director Financiero) automatizado para **Tacos Aragón**, una taquería en Culiacán, Sinaloa.

Implementa un sistema de **dos agentes de IA en paralelo**:

| Agente | Modelo | Responsabilidad |
|--------|--------|-----------------|
| Descarga y parseo fiscal | Gemini | Autenticación SAT, descarga de CFDIs en XML, parseo de comprobantes |
| Análisis contable y fiscal | Claude (Anthropic) | Estado de resultados, balance general, cálculo ISR/IVA, análisis de inventario, chat CFO |

---

## Arquitectura

```
cfo_aragon_agent/
├── main.py                  # FastAPI app, middlewares, auth, health
├── agents/
│   ├── cfo_agent.py         # Agente Claude: P&L, balance, inventario, chat
│   └── tax_agent.py         # Agente dual: Gemini descarga SAT + Claude analiza CFDIs
├── routes/
│   ├── contabilidad.py      # /api/contabilidad — ingresos, gastos, estado de resultados
│   ├── impuestos.py         # /api/impuestos — CFDIs, declaraciones, XLSX fiscal
│   ├── inventario.py        # /api/inventario — CRUD + análisis Claude
│   └── config.py            # /api/config — actualización de credenciales SAT/Gmail
├── db/
│   ├── database.py          # SQLite con SQLAlchemy
│   └── models.py            # Tablas: Ingreso, Gasto, InventarioItem, AnalisisFiscal, DeclaracionMensual
├── requirements.txt
├── .env.example             # Variables de entorno requeridas (sin valores reales)
└── ecosystem.config.js      # Configuración PM2 (NO incluir en git — contiene credenciales)
```

---

## Endpoints principales

### Contabilidad (`/api/contabilidad`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/ingresos` | Lista ingresos (filtro `desde`, `hasta`) |
| POST | `/ingresos` | Registra un ingreso |
| DELETE | `/ingresos/{id}` | Elimina un ingreso |
| GET | `/gastos` | Lista gastos |
| POST | `/gastos` | Registra un gasto |
| DELETE | `/gastos/{id}` | Elimina un gasto |
| POST | `/estado-resultados` | Claude genera el Estado de Resultados |
| POST | `/balance` | Claude genera el Balance General |
| POST | `/chat` | Chat libre con el agente CFO |

### Impuestos (`/api/impuestos`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/analizar` | Descarga CFDIs del SAT y genera análisis fiscal con Claude |
| GET | `/resultado` | Último análisis guardado (filtro por `mes`) |
| GET | `/historial` | Lista los últimos 24 análisis |
| POST | `/chat` | Chat fiscal con Claude |
| POST | `/subir-xml` | Sube XMLs o ZIPs de retenciones manuales |
| GET | `/manuales/{mes}` | Lista XMLs subidos manualmente |
| DELETE | `/manuales/{mes}/{filename}` | Elimina XML manual |
| POST | `/exportar-xlsx` | Genera Excel fiscal del mes (SAT + Gmail + manuales) |
| GET | `/descargar/{filename}` | Descarga el Excel generado |
| POST | `/declaracion` | Crea/actualiza declaración mensual (upsert) |
| GET | `/declaracion/{mes}` | Obtiene declaración del mes |
| GET | `/declaraciones/{anio}` | Lista declaraciones del año con totales |
| PATCH | `/declaracion/{mes}/pagar` | Marca ISR o IVA como pagado |
| GET | `/vencimientos` | Próximos 3 meses con estado y urgencia |
| GET | `/anual/{anio}` | Resumen anual con proyección y alerta $300K |
| GET | `/gastos-recurrentes/{mes}` | Proveedores recurrentes sin CFDI en el mes |

### Inventario (`/api/inventario`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Lista inventario con alertas de mínimo |
| POST | `/` | Crea ítem |
| PUT | `/{id}` | Actualiza ítem completo |
| PATCH | `/{id}/cantidad` | Actualiza solo la cantidad |
| DELETE | `/{id}` | Elimina ítem |
| GET | `/analisis` | Claude analiza el inventario y detecta alertas |

### Configuración (`/api/config`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/credenciales` | Muestra credenciales activas (enmascaradas) |
| PUT | `/credenciales` | Actualiza credenciales SAT o Gmail en caliente |

### General

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| GET | `/docs` | Documentación Swagger automática |
| POST | `/api/cfo/chat` | Chat CFO libre |

---

## Variables de entorno

Copia `.env.example` a `.env` y completa los valores:

```bash
cp .env.example .env
```

| Variable | Descripción |
|----------|-------------|
| `API_TOKEN` | Token secreto para autenticar peticiones (`x-api-token` header) |
| `SAT_RFC` | RFC del contribuyente (ej. `GOAG941101R17`) |
| `SAT_KEY_PASSWORD` | Contraseña del archivo `.key` del SAT |
| `SAT_CER_PATH` | Ruta absoluta al archivo `firma.cer` |
| `SAT_KEY_PATH` | Ruta absoluta al archivo `firma.key` |
| `GEMINI_API_KEY` | API key de Google Gemini |
| `ANTHROPIC_API_KEY` | API key de Anthropic (Claude) |
| `EMAIL_USER` | Correo Gmail para recibir retenciones de apps |
| `EMAIL_PASS` | Contraseña de aplicación Gmail (no la contraseña normal) |
| `IMAP_SERVER` | Servidor IMAP (default: `imap.gmail.com`) |
| `TAX_BOT_PATH` | Ruta absoluta al repositorio `tax_aragon_bot` |
| `PORT` | Puerto del servidor (default: `3002`) |

---

## Instalación

```bash
# 1. Clonar
git clone <repo-url>
cd cfo_aragon_agent

# 2. Entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Dependencias
pip install -r requirements.txt

# 4. Variables de entorno
cp .env.example .env
# Editar .env con los valores reales

# 5. Ejecutar
python main.py
```

El servidor estará disponible en `http://localhost:3002`.
Documentación Swagger: `http://localhost:3002/docs`

### Con PM2 (producción)

```bash
# Copiar ecosystem.config.js.example y configurar credenciales
pm2 start ecosystem.config.js
pm2 save
```

---

## Seguridad

- Todas las rutas (excepto `/health` y `/docs`) requieren el header `x-api-token`.
- Las credenciales SAT nunca se exponen en los endpoints — se enmascaran al consultar `/api/config/credenciales`.
- El `.env` y `ecosystem.config.js` están en `.gitignore` y nunca deben subirse al repositorio.
- Rate limiting activo mediante `slowapi`.

---

## Sincronización con tacos-aragon-app

La app frontend de Tacos Aragón consume esta API en el puerto `3002`. Los módulos clave que la app utiliza:

| Función de la app | Endpoint del CFO Agent |
|-------------------|------------------------|
| Registrar venta del día | `POST /api/contabilidad/ingresos` |
| Registrar gasto | `POST /api/contabilidad/gastos` |
| Ver P&L del mes | `POST /api/contabilidad/estado-resultados` |
| Control de inventario | `GET/POST/PATCH /api/inventario/` |
| Análisis fiscal mensual | `POST /api/impuestos/analizar` |
| Ver declaraciones | `GET /api/impuestos/declaracion/{mes}` |
| Alertas de vencimientos | `GET /api/impuestos/vencimientos` |
| Exportar Excel fiscal | `POST /api/impuestos/exportar-xlsx` |
| Chat con CFO | `POST /api/cfo/chat` |

La app también depende del módulo **tax_aragon_bot** (ruta configurada en `TAX_BOT_PATH`) para acceder a los parsers de XML del SAT y al exportador de Excel.

---

## Régimen fiscal

Tacos Aragón opera bajo **régimen dual**:

- **Actividades Empresariales** — Arts. 100-110 LISR
- **Plataformas Tecnológicas** — Arts. 113-A a 113-C LISR (Didi Food, Uber Eats, Rappi)

Retención ISR plataformas: **2.1%** (Fracción I — entrega de alimentos)
IVA retenido por apps: **50% × 16% = 8%**
Vencimiento declaración provisional: **día 17 de cada mes**
