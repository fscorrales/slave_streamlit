# PLAN MAESTRO: Migración Slave VB6 a Streamlit + API Koyeb (Poetry + HTTPX)

## 1. Contexto y Objetivos
Migrar el sistema legacy 'slave_vb6' a una aplicación local ejecutable construida en Python Streamlit, gestionando dependencias con Poetry y empacable vía PyInstaller (`run_app.py`). La persistencia se realiza llamando a la API remota en Koyeb (FastAPI + MongoDB).

## 2. Gestión de Entorno y Dependencias (Poetry)
- **Gestor:** Poetry (`pyproject.toml` / `poetry.lock`).
- **Dependencias principales:**
  - `streamlit`
  - `httpx`
  - `pandas`
  - `pydantic`
  - `python-dotenv`
- **Dependencias de desarrollo (dev):**
  - `pyinstaller`

## 3. Arquitectura del Proyecto
proyecto_slave/
├── pyproject.toml             # Configuración de dependencias de Poetry
├── poetry.lock
├── app.py                     # Entrypoint Streamlit (Navegación / Dashboard)
├── run_app.py                 # Wrapper ejecutable para PyInstaller
├── .env                       # API_BASE_URL=https://fixed-marita-invico-d13e43fa.koyeb.app
├── models/
│   ├── __init__.py
│   └── schemas.py             # Pydantic models (FactureroReport, HonorarioReport)
├── services/
│   ├── __init__.py
│   └── api_slave.py           # Requests a la API con httpx
├── components/
│   ├── csv_importer.py        # Parseo y validación de CSVs
│   └── forms.py               # Asignación manual de estructura por CUIT
└── utils/
    └── config.py

## 4. Especificaciones de Datos
- **FactureroReport:** cuit (str), nombre (str), estructura (str).
- **HonorarioReport:** ejercicio (int), mes (str), fecha (datetime), nro_comprobante (str), tipo (str), cuit (str), actividad (str), partida (str), importe_bruto (float), retenciones (iibb, lp, sellos, seguro, otras_retenciones, anticipo, descuento, mutual, embargo).

## 5. Tareas de Implementación para Antigravity
1. Inicializar el proyecto con Poetry (`poetry init`) e instalar todas las dependencias nombradas (usando `httpx` en lugar de `requests`).
2. Crear los esquemas de datos Pydantic en `models/schemas.py`.
3. Crear `services/api_slave.py` usando `httpx.Client` para consumir los endpoints `/slave` de la API en Koyeb.
4. Crear la interfaz Streamlit con dos secciones principales:
   - **Carga de Honorarios:** Subida de CSV de comprobantes + inputs manuales globales (`ejercicio`, `mes`, `fecha`, `nro_comprobante`).
   - **Padrón de Factureros:** Importación CSV y formulario/editor para asignar la `estructura` presupuestaria por CUIT.
5. Crear `run_app.py` y verificar la compilación ejecutando PyInstaller dentro del entorno de Poetry (`poetry run pyinstaller ...`).