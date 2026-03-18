# CFO Aragón Agent

FastAPI server on port **3002** acting as an automated CFO (Chief Financial Officer) for **Tacos Aragón**, a taquería in Culiacán, Sinaloa.

Implements a **dual intelligent agent** system:

| Agent | Responsibility |
|-------|----------------|
| Tax download and parsing | SAT authentication, CFDI XML download, invoice parsing |
| Accounting and fiscal analysis | Income statement, balance sheet, ISR/IVA calculation, inventory analysis, CFO chat |

---

## Architecture

```
cfo_aragon_agent/
├── main.py                  # FastAPI app, middlewares, auth, health
├── agents/
│   ├── cfo_agent.py         # CFO agent: P&L, balance, inventory, chat
│   └── tax_agent.py         # Dual agent: SAT download + CFDI analysis
├── routes/
│   ├── contabilidad.py      # /api/contabilidad — income, expenses, income statement
│   ├── impuestos.py         # /api/impuestos — CFDIs, declarations, fiscal XLSX
│   ├── inventario.py        # /api/inventario — CRUD + analysis
│   └── config.py            # /api/config — SAT/Gmail credential update
├── db/
│   ├── database.py          # SQLite with SQLAlchemy
│   └── models.py            # Tables: Ingreso, Gasto, InventarioItem, AnalisisFiscal, DeclaracionMensual
├── utils/
│   └── tiempo.py            # Timezone utilities (GMT-7 / America/Hermosillo)
├── requirements.txt
├── .env.example             # Required environment variables (no real values)
└── ecosystem.config.js      # PM2 configuration (NOT in git — contains credentials)
```

---

## Main endpoints

### Accounting (`/api/contabilidad`)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/ingresos` | List income (filter `desde`, `hasta`) |
| POST | `/ingresos` | Record income |
| DELETE | `/ingresos/{id}` | Delete income |
| GET | `/gastos` | List expenses |
| POST | `/gastos` | Record expense |
| DELETE | `/gastos/{id}` | Delete expense |
| POST | `/estado-resultados` | Generate Income Statement |
| POST | `/balance` | Generate Balance Sheet |
| POST | `/chat` | Free chat with the CFO agent |

### Taxes (`/api/impuestos`)

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/analizar` | Download CFDIs from SAT and generate fiscal analysis |
| GET | `/resultado` | Last saved analysis (filter by `mes`) |
| GET | `/historial` | List last 24 analyses |
| POST | `/chat` | Fiscal chat |
| POST | `/subir-xml` | Upload XMLs or ZIPs of manual retentions |
| GET | `/manuales/{mes}` | List manually uploaded XMLs |
| DELETE | `/manuales/{mes}/{filename}` | Delete manual XML |
| POST | `/exportar-xlsx` | Generate fiscal Excel (SAT + Gmail + manual) |
| GET | `/descargar/{filename}` | Download generated Excel |
| POST | `/declaracion` | Create/update monthly declaration (upsert) |
| GET | `/declaracion/{mes}` | Get declaration for the month |
| GET | `/declaraciones/{anio}` | List declarations for the year with totals |
| PATCH | `/declaracion/{mes}/pagar` | Mark ISR or IVA as paid |
| GET | `/vencimientos` | Next 3 months with status and urgency |
| GET | `/anual/{anio}` | Annual summary with projection and $300K alert |
| GET | `/gastos-recurrentes/{mes}` | Recurring vendors without CFDI in the month |

### Inventory (`/api/inventario`)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | List inventory with minimum alerts |
| POST | `/` | Create item |
| PUT | `/{id}` | Update item |
| PATCH | `/{id}/cantidad` | Update quantity only |
| DELETE | `/{id}` | Delete item |
| GET | `/analisis` | Analyze inventory and detect alerts |

### Configuration (`/api/config`)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/credenciales` | Show active credentials (masked) |
| PUT | `/credenciales` | Update SAT or Gmail credentials at runtime |

### General

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/health` | Service status |
| GET | `/docs` | Automatic Swagger documentation |
| POST | `/api/cfo/chat` | Free CFO chat |

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `API_TOKEN` | Secret token for request authentication (`x-api-token` header) |
| `SAT_RFC` | Taxpayer RFC (e.g. `GOAG941101R17`) |
| `SAT_KEY_PASSWORD` | Password for the SAT `.key` file |
| `SAT_CER_PATH` | Absolute path to `firma.cer` |
| `SAT_KEY_PATH` | Absolute path to `firma.key` |
| `GEMINI_API_KEY` | Google AI API key (SAT download and XML parsing) |
| `ANTHROPIC_API_KEY` | NLP API key (accounting and fiscal analysis) |
| `EMAIL_USER` | Gmail address for receiving app retentions |
| `EMAIL_PASS` | Gmail app password (not the regular password) |
| `IMAP_SERVER` | IMAP server (default: `imap.gmail.com`) |
| `TAX_BOT_PATH` | Absolute path to the `tax_aragon_bot` repository |
| `PORT` | Server port (default: `3002`) |

---

## Installation

```bash
# 1. Clone
git clone <repo-url>
cd cfo_aragon_agent

# 2. Virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment variables
cp .env.example .env
# Edit .env with real values

# 5. Run
python main.py
```

Server available at `http://localhost:3002`.
Swagger docs: `http://localhost:3002/docs`

### With PM2 (production)

```bash
# Copy ecosystem.config.js.example and configure credentials
pm2 start ecosystem.config.js
pm2 save
```

---

## Security

- All routes (except `/health` and `/docs`) require the `x-api-token` header.
- SAT credentials are never exposed in endpoints — they are masked when querying `/api/config/credenciales`.
- `.env` and `ecosystem.config.js` are in `.gitignore` and must never be committed.
- Rate limiting active via `slowapi`.

---

## Sync with tacos-aragon-app

The Tacos Aragón frontend app consumes this API on port `3002`. Key modules the app uses:

| App function | CFO Agent endpoint |
|---|---|
| Record daily sales | `POST /api/contabilidad/ingresos` |
| Record expense | `POST /api/contabilidad/gastos` |
| View monthly P&L | `POST /api/contabilidad/estado-resultados` |
| Inventory control | `GET/POST/PATCH /api/inventario/` |
| Monthly fiscal analysis | `POST /api/impuestos/analizar` |
| View declarations | `GET /api/impuestos/declaracion/{mes}` |
| Payment deadline alerts | `GET /api/impuestos/vencimientos` |
| Export fiscal Excel | `POST /api/impuestos/exportar-xlsx` |
| CFO chat | `POST /api/cfo/chat` |

The app also depends on the **tax_aragon_bot** module (path configured in `TAX_BOT_PATH`) to access the SAT XML parsers and Excel exporter.

---

## Tax regime

Tacos Aragón operates under a **dual regime**:

- **Business Activities** — Arts. 100-110 LISR
- **Technology Platforms** — Arts. 113-A to 113-C LISR (Didi Food, Uber Eats, Rappi)

ISR retention on platforms: **2.1%** (Section I — food delivery)
IVA retained by apps: **50% × 16% = 8%**
Provisional declaration due: **17th of each month**

---

---

# CFO Aragón Agent (ES)

Servidor FastAPI en el puerto **3002** que actúa como CFO (Director Financiero) automatizado para **Tacos Aragón**, una taquería en Culiacán, Sinaloa.

Implementa un sistema de **dos agentes inteligentes en paralelo**:

| Agente | Responsabilidad |
|--------|-----------------|
| Descarga y parseo fiscal | Autenticación SAT, descarga de CFDIs en XML, parseo de comprobantes |
| Análisis contable y fiscal | Estado de resultados, balance general, cálculo ISR/IVA, análisis de inventario, chat CFO |

---

## Arquitectura

```
cfo_aragon_agent/
├── main.py                  # FastAPI app, middlewares, auth, health
├── agents/
│   ├── cfo_agent.py         # Agente CFO: P&L, balance, inventario, chat
│   └── tax_agent.py         # Agente dual: descarga SAT + análisis CFDIs
├── routes/
│   ├── contabilidad.py      # /api/contabilidad — ingresos, gastos, estado de resultados
│   ├── impuestos.py         # /api/impuestos — CFDIs, declaraciones, XLSX fiscal
│   ├── inventario.py        # /api/inventario — CRUD + análisis
│   └── config.py            # /api/config — actualización de credenciales SAT/Gmail
├── db/
│   ├── database.py          # SQLite con SQLAlchemy
│   └── models.py            # Tablas: Ingreso, Gasto, InventarioItem, AnalisisFiscal, DeclaracionMensual
├── utils/
│   └── tiempo.py            # Utilidades de zona horaria (GMT-7 / America/Hermosillo)
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
| POST | `/estado-resultados` | Genera el Estado de Resultados |
| POST | `/balance` | Genera el Balance General |
| POST | `/chat` | Chat libre con el agente CFO |

### Impuestos (`/api/impuestos`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/analizar` | Descarga CFDIs del SAT y genera análisis fiscal |
| GET | `/resultado` | Último análisis guardado (filtro por `mes`) |
| GET | `/historial` | Lista los últimos 24 análisis |
| POST | `/chat` | Chat fiscal |
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
| GET | `/analisis` | Analiza el inventario y detecta alertas |

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
| `GEMINI_API_KEY` | API key de Google AI (descarga SAT y parseo XML) |
| `ANTHROPIC_API_KEY` | API key del agente de análisis fiscal/contable |
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
