"""
Servicio de transformación de DataFrames crudos (CSV legados del
sistema anterior) a DataFrames estructurados según los modelos
Pydantic de ``models/schemas.py``.

No importa ``streamlit`` ni realiza llamadas HTTP (AGENTS.md §1).
"""

__all__ = [
    "process_informe_por_destino",
    "merge_informe_con_precarizados",
    "construir_payload_honorarios",
]


from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from models.schemas import HonorarioReport, InformePorDestino
from utils.handling_files import read_csv_file
from utils.transform_data import normalize_name_for_match

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
# ``mutual`` y ``embargo`` no existen en el
# reporte -> se inicializan en 0.0 (campos no ``Optional``).
# --------------------------------------------------
_MAPEO_COLUMNAS: dict[str, int] = {
    "nombre_completo": 28,  # Proveedor
    "importe_bruto": 31,  # Monto Imponible
    "sellos": 32,  # Sellos
    "lp": 33,  # L. Pago
    "iibb": 34,  # IB
    "otras_retenciones": 36,  # O. Ret.
    "anticipo": 37,  # Antic.
    "seguro": 38,  # Seguro
    "descuento": 39,  # No existe en el reporte -> 0.0
}

# Campos del modelo sin contraparte en el reporte -> 0.0
_CAMPOS_SIN_DATO: tuple[str, ...] = ("mutual", "embargo")

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
def _texto_limpio(valor: object) -> str:
    """
    Convierte un escalar de pandas/numpy a ``str`` saneado.

    Normaliza ``None``/``NaN``/``pd.NA`` a cadena vacía y recorta la
    parte decimal de los floats enteros (p.ej. ``354.0`` -> ``"354"``)
    para coincidir con el valor canónico del padrón.

    Args:
        valor: Cualquier escalar proveniente de una fila.

    Returns:
        Cadena limpia (vacía si el valor era nulo).
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


# --------------------------------------------------
def merge_informe_con_precarizados(
    df_informe: pd.DataFrame,
    df_precarizados: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Cruza el informe por destino con el padrón de precarizados para
    completar ``cuit`` / ``actividad`` / ``partida``.

    El cruce se hace por ``nombre_completo`` usando
    :func:`utils.transform_data.normalize_name_for_match` como clave
    normalizada (tolera comas, prefijos ``(JUBILADO)``/``[LP]``,
    mayúsculas distintas, etc.), igual que en la migración.

    Args:
        df_informe: Salida de :func:`process_informe_por_destino`.
        df_precarizados: Padrón de la colección ``factureros``
            (columnas ``nombre_completo``, ``cuit``, ``actividad``,
            ``partida``).

    Returns:
        Tupla ``(merged, sin_match, incompletos)``:

        - ``merged``: el informe enriquecido con las columnas del
          padrón (``_match_key`` eliminada).
        - ``sin_match``: nombres ordenados y sin duplicados de
          agentes **ausentes** en el padrón. Deben darse de alta
          manualmente.
        - ``incompletos``: nombres ordenados y sin duplicados de
          agentes **presentes** pero sin ``cuit``/``actividad``/
          ``partida``. Deben completarse en el padrón (el ``cuit``
          es obligatorio en ``HonorarioReport``).

        Ambas listas vacías => se puede continuar sin obstáculos.
    """
    if df_informe.empty:
        return pd.DataFrame(), [], []

    df_inf: pd.DataFrame = df_informe.copy()
    df_inf["_match_key"] = df_inf["nombre_completo"].apply(normalize_name_for_match)

    # Padrón vacío: ningún agente puede resolverse.
    if df_precarizados.empty:
        sin_match = sorted(
            set(df_informe["nombre_completo"].astype(str).str.strip()) - {""}
        )
        return df_inf.drop(columns=["_match_key"]), sin_match, []

    # Sólo las columnas útiles del padrón: evita la colisión de
    # ``nombre_completo`` al hacer merge sobre ``_match_key``.
    columnas_padron: list[str] = [
        columna
        for columna in ("nombre_completo", "cuit", "actividad", "partida")
        if columna in df_precarizados.columns
    ]
    df_pad: pd.DataFrame = df_precarizados[columnas_padron].copy()
    # Defensa: si la API no trajo alguna columna, se crea vacía para
    # que la clasificación la detecte como "incompleto".
    for columna in ("cuit", "actividad", "partida"):
        if columna not in df_pad.columns:
            df_pad[columna] = pd.NA

    df_pad["_match_key"] = df_pad["nombre_completo"].apply(normalize_name_for_match)
    # Un agente repetido en el padrón: nos quedamos con el primero.
    df_pad = df_pad.drop_duplicates(subset=["_match_key"], keep="first")

    lookup: pd.DataFrame = df_pad[["_match_key", "cuit", "actividad", "partida"]]
    merged: pd.DataFrame = df_inf.merge(lookup, on="_match_key", how="left")

    # ── Clasificación de agentes ──
    # "Existe" se determina por actividad/partida (obligatorios en
    # FactureroReport): si traen nulo, el merge no encontró fila.
    existe = merged["actividad"].notna() & merged["partida"].notna()

    def _falta(columna: str) -> pd.Series:
        serie = merged[columna]
        return serie.isna() | serie.astype(str).str.strip().isin(
            ["", "nan", "None", "<NA>"]
        )

    incompleto = _falta("cuit") | _falta("actividad") | _falta("partida")

    sin_match = sorted(
        set(merged.loc[~existe, "nombre_completo"].astype(str)) - {"", "nan"}
    )
    incompletos = sorted(
        set(merged.loc[existe & incompleto, "nombre_completo"].astype(str))
        - {"", "nan"}
    )

    merged = merged.drop(columns=["_match_key"])
    return merged, sin_match, incompletos


# --------------------------------------------------
def process_informe_por_destino(
    dataframe: pd.DataFrame | str | Path | BytesIO | None = None,
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
            - ``BytesIO``: buffer en memoria (p.ej. ``BytesIO(f.getvalue())``
              con el archivo de ``st.file_uploader``, cuyo
              ``UploadedFile`` hereda de ``BytesIO``).
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
    elif isinstance(dataframe, (str, Path, BytesIO)):
        # Ruta a un CSV **o** buffer en memoria (``st.file_uploader``
        # devuelve un ``UploadedFile`` que hereda de ``BytesIO``).
        # Sin esta rama, un ``BytesIO`` caería en el ``isinstance``
        # de más abajo y se devolvería un DataFrame vacío.
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


# --------------------------------------------------
def construir_payload_honorarios(
    df_merged: pd.DataFrame,
    *,
    ejercicio: int,
    mes: str,
    fecha: datetime,
    nro_comprobante: str,
    cta_cte: str,
    tipo: str,
) -> list[dict[str, Any]]:
    """
    Construye la lista de registros lista para
    ``POST /slave/honorarios/add_many/{nro_comprobante}``.

    Cada registro se valida contra :class:`HonorarioReport` antes de
    retornarse, de modo que un esquema incompleto se detecta en el
    cliente y no como un error 4xx de la API.

    Args:
        df_merged: Salida de :func:`merge_informe_con_precarizados`
            ya sin filas sin match/incompletas.
        ejercicio: Ejercicio derivado del año de la fecha.
        mes: Mes en formato ``"%m/%Y"``.
        fecha: Fecha del comprobante (se envía como ``datetime``).
        nro_comprobante: Comprobante completo ``"00000/yy"``.
        cta_cte: Cuenta corriente (e.g. ``"130832-05"``).
        tipo: Tipo de comprobante.

    Returns:
        Lista de dicts compatibles con ``HonorarioReport``.

    Raises:
        pydantic.ValidationError: Si alguna fila no cumple el
            esquema. El llamador debe informarlo y NO enviar nada.
    """
    campos_monto: tuple[str, ...] = (
        "importe_bruto",
        "iibb",
        "lp",
        "sellos",
        "seguro",
        "otras_retenciones",
        "anticipo",
        "descuento",
        "mutual",
        "embargo",
    )

    registros: list[dict[str, Any]] = []
    for fila in df_merged.to_dict(orient="records"):
        registro: dict[str, Any] = {
            "ejercicio": int(ejercicio),
            "mes": str(mes),
            "fecha": fecha,
            "nro_comprobante": str(nro_comprobante),
            "cta_cte": str(cta_cte),
            "tipo": str(tipo),
            "cuit": _texto_limpio(fila.get("cuit")),
            "nombre_completo": _texto_limpio(fila.get("nombre_completo")),
            "actividad": _texto_limpio(fila.get("actividad")),
            "partida": _texto_limpio(fila.get("partida")),
        }
        for campo in campos_monto:
            valor = fila.get(campo, 0.0)
            registro[campo] = float(valor) if pd.notna(valor) else 0.0
        registro["updated_at"] = datetime.now()

        # Validación estricta contra el esquema del modelo.
        HonorarioReport.model_validate(registro)
        registros.append(registro)

    return registros
