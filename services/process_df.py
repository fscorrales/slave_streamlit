"""
Servicio de transformación de DataFrames crudos (CSV legados del
sistema anterior) a DataFrames estructurados según los modelos
Pydantic de ``models/schemas.py``.

No importa ``streamlit`` ni realiza llamadas HTTP (AGENTS.md §1).
"""

__all__ = ["process_informe_por_destino"]


from pathlib import Path

import pandas as pd

from models.schemas import InformePorDestino
from utils.handling_files import read_csv_file

# --------------------------------------------------
# Estructura del reporte "Resumen de Pagos por Destino"
# --------------------------------------------------
# El CSV crudo se lee con ``read_csv_file``, que normaliza los
# nombres de columna a índices numéricos de cadena
# (``"0".."99"``). Cada fila del reporte contiene:
#
#   - Posiciones  0..9  : metadatos (institución, título, fechas,
#                          filtros). El título está en la 1.
#   - Posiciones 10..25 : encabezados repetidos en cada fila
#                          (no son datos).
#   - Posiciones 26..40 : datos del registro individual.
#   - Posición      41  : literal "TOTALES" (marcador).
#   - Posiciones 42..50 : totales globales (constantes).
#   - Posiciones 51..52 : pie de página.
#
# Mapeo de datos a campos del modelo ``InformePorDestino``.
# Salvedades verificadas empíricamente sobre
# ``services/informe_por_destino.csv``:
#
#   1. ``Firma`` (encabezado 18 / dato 34) NO forma parte del
#      modelo, por lo que las retenciones quedan en 34..39.
#   2. La posición 40 es el **NETO A PAGAR** (validado con
#      ``Monto - (32 + 33 + 34 + 38 + 39) == pos40`` en todas
#      las filas), NO un descuento. No se mapea al modelo.
#
# ``descuento``, ``mutual`` y ``embargo`` no existen en el
# reporte -> se inicializan en 0.0 (campos no ``Optional``).
# --------------------------------------------------
_MAPEO_COLUMNAS: dict[str, int] = {
    "nombre_completo": 28,  # Proveedor
    "importe_bruto": 31,  # Monto Imponible
    "sellos": 34,  # Sellos
    "lp": 35,  # L. Pago
    "iibb": 36,  # IB
    "otras_retenciones": 37,  # O. Ret.
    "anticipo": 38,  # Antic.
    "seguro": 39,  # Seguro
}

# Campos del modelo sin contraparte en el reporte -> 0.0
_CAMPOS_SIN_DATO: tuple[str, ...] = ("descuento", "mutual", "embargo")

# Título que identifica al reporte esperado (posición 1).
_TITULO_ESPERADO: str = "Resumen de Pagos por Destino"

# Archivo por defecto cuando no se provee ningún argumento.
_DEFAULT_CSV: Path = Path(__file__).resolve().parent / "informe_por_destino.csv"


# --------------------------------------------------
def _parse_moneda(valor: object) -> float:
    """
    Convierte un monto con formato argentino a ``float``.

    Ejemplos:
        ``"1,770,025.00"`` -> ``1770025.0``
        ``"8,850.13"``     -> ``8850.13``
        ``"TOTALES"``      -> ``0.0``
        ``""``             -> ``0.0``

    Args:
        valor: Celda cruda (cualquier tipo).

    Returns:
        El monto como ``float``. ``0.0`` si el valor no es
        numérico o está vacío (nunca lanza excepción, para no
        interrumpir la transformación de filas vecinas válidas).
    """
    if pd.isna(valor):
        return 0.0
    texto: str = str(valor).strip().replace(",", "")
    if texto in ("", "-", "TOTALES", "nan", "NaN"):
        return 0.0
    try:
        return float(texto)
    except ValueError:
        return 0.0



# --------------------------------------------------
def process_informe_por_destino(
    dataframe: pd.DataFrame | str | Path | None = None,
) -> pd.DataFrame:
    """
    Lee y convierte el reporte "Resumen de Pagos por Destino" en un
    ``DataFrame`` con las columnas del modelo ``InformePorDestino``.

    Diseñada para ser usada como ``uploader_func`` de
    ``views/aux_tables.report_template()``, que invoca
    ``read_csv_file(uploaded_file)`` y luego pasa el ``DataFrame``
    crudo (columnas ``"0".."99"``) a esta función.

    Args:
        dataframe: Una de las siguientes entradas:

            - ``pd.DataFrame``: DataFrame crudo leído con
              ``read_csv_file`` (caso principal, desde
              ``report_template()`` con ``uploaded_file``).
            - ``str | Path``: Ruta a un CSV, que se lee con
              ``read_csv_file``.
            - ``None``: se lee ``services/informe_por_destino.csv``
              (conveniencia para pruebas directas).

    Returns:
        DataFrame con las columnas de ``InformePorDestino`` en el
        orden exacto del modelo (``nombre_completo: str`` y montos
        ``float``). Vacío si la entrada no es un reporte válido
        (título incorrecto, columnas faltantes o sin registros).

    Raises:
        Ninguna. Los casos inválidos devuelven ``pd.DataFrame()``
        vacío para que el caller (``report_template()``) muestre el
        mensaje de "CSV Vacío o Incorrecto".
    """
    # ── 1. Resolver la entrada a un DataFrame crudo ──────────
    if dataframe is None:
        dataframe = read_csv_file(_DEFAULT_CSV)
    elif isinstance(dataframe, (str, Path)):
        dataframe = read_csv_file(dataframe)

    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return pd.DataFrame()

    if dataframe.shape[1] < 2:
        # No hay ni siquiera la columna del título (posición 1).
        return pd.DataFrame()

    df: pd.DataFrame = dataframe.copy()

    # ── 2. Validar que sea el reporte esperado ───────────────
    titulo_reporte: str = str(df.iloc[0, 1]).strip()
    if not titulo_reporte.startswith(_TITULO_ESPERADO):
        print(
            f"⚠️ Título de reporte inesperado: '{titulo_reporte}'. "
            f"Se esperaba '{_TITULO_ESPERADO}'."
        )
        return pd.DataFrame()

    # ── 3. Validar que existan las columnas requeridas ───────
    columnas_requeridas: list[str] = [str(pos) for pos in _MAPEO_COLUMNAS.values()]
    faltantes: list[str] = [
        columna for columna in columnas_requeridas if columna not in df.columns
    ]
    if faltantes:
        print(
            f"⚠️ Faltan columnas {faltantes} en el DataFrame crudo "
            f"(se esperan posiciones numéricas '0'..'99' provenientes "
            f"de read_csv_file)."
        )
        return pd.DataFrame()

    # ── 4. Extraer y convertir los campos del modelo ─────────
    resultado: pd.DataFrame = pd.DataFrame()

    # nombre_completo: se limpia y normaliza a str.
    posicion_nombre: int = _MAPEO_COLUMNAS["nombre_completo"]
    resultado["nombre_completo"] = df[str(posicion_nombre)].astype(str).str.strip()

    # Montos: de string "1,770,025.00" a float.
    for campo, posicion in _MAPEO_COLUMNAS.items():
        if campo == "nombre_completo":
            continue
        resultado[campo] = df[str(posicion)].apply(_parse_moneda)

    # Campos sin contraparte en el reporte -> 0.0 (modelo no-Optional).
    for campo in _CAMPOS_SIN_DATO:
        resultado[campo] = 0.0

    # ── 5. Filtrar filas sin proveedor ───────────────────────
    resultado = resultado.loc[
        (resultado["nombre_completo"] != "")
        & (resultado["nombre_completo"] != "nan")
        & (resultado["nombre_completo"] != "None")
    ].copy()

    if resultado.empty:
        print("⚠️ No se encontraron registros válidos en el reporte.")
        return pd.DataFrame()

    # ── 6. Reordenar según el orden exacto del modelo ────────
    orden_modelo: list[str] = list(InformePorDestino.model_fields.keys())
    resultado = resultado.loc[:, orden_modelo].reset_index(drop=True)

    # ── 7. Asegurar tipos compatibles con el modelo ──────────
    resultado["nombre_completo"] = resultado["nombre_completo"].astype(str)
    for campo in orden_modelo:
        if campo != "nombre_completo":
            resultado[campo] = resultado[campo].astype(float)

    return resultado

