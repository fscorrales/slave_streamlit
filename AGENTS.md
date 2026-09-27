# AGENT RULES: Estándares de Calidad y Arquitectura

## 1. Separación Estricta de Responsabilidades (SoC)
- **Módulos de UI (Streamlit):** Los archivos dentro de `components/`, `pages/` y `app.py` se limitarán EXCLUSIVAMENTE a la renderización de componentes visuales, captura de eventos y gestión de estado (`st.session_state`)[cite: 1].
- **Módulos de Servicio (`services/`):** La comunicación HTTP con la API en Koyeb debe residir en `services/api_slave.py`[cite: 1]. Queda **estrictamente prohibido** importar `streamlit` en la carpeta `services/` o `models/`.
- **Módulos de Modelos (`models/`):** Los modelos de datos Pydantic deberán estar aislados en `models/schemas.py`[cite: 1].

## 2. Estilo de Código Python (PEP 8)
- **Formateo:** Cumplimiento estricto de PEP 8. Usar exactamente 4 espacios por nivel de sangría.
- **Nombres:** Usar `snake_case` para variables/funciones, `CamelCase` para clases y `UPPER_CASE` para constantes. EVITAR variables de una sola letra.
- **Tipado Estático (Type Hints):** Todas las firmas de funciones y métodos deben incluir *type hints* explícitos.

## 3. Manejo Riguroso de Errores y Excepciones
- **Prohibido Silenciar Errores:** Queda prohibido el uso de bloques `try...except` vacíos o capturas genéricas que silenciadores.
- **Propagación desde HTTPX hacia la UI:**
  1. En `services/api_slave.py`, capturar errores HTTP de `httpx` (`httpx.HTTPStatusError`, `httpx.RequestError`) y re-elevarlos o transformarlos.
  2. La UI en Streamlit debe capturar estas excepciones y mostrar mensajes explicativos al usuario mediante `st.error()`.

## 4. Control de Cambios y Git (Límites)
- Queda **prohibido** ejecutar comandos de Git autónomos (`git add`, `git commit`, `git push`) sin la autorización explícita del usuario.