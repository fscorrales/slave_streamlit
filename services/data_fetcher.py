"""Servicio de fetching de datos para la UI.

Aplica ``@st.cache_data`` directamente sobre las funciones de servicio
(tal como autoriza ``AGENTS.md`` §1: *"Se autoriza el uso de
``@st.cache_data`` / ``@st.cache_resource`` para optimizar peticiones"*),
de modo que la capa de ``views/`` no necesita wrappers intermedios.

Mantiene un fallback a caché Parquet local cuando la API no está
disponible (modo degradado) y **no** contiene widgets interactivos de
entrada de datos (``st.button``, ``st.text_input``, ``st.file_uploader``),
los cuales pertenecen a la capa de UI (``AGENTS.md`` §1).
"""

__all__ = [
    "get_precarizados",
    "get_referencias_factureros",
    "get_referencias_honorarios",
    "get_ejercicios_list",
    "get_honorarios",
]

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

import utils.exceptions as ex
from services.api_slave import fetch_dataframe
from utils.endpoints import Endpoints
from utils.handling_path import get_cache_path

logger = logging.getLogger(__name__)


# --------------------------------------------------
def _valores_unicos(df: pd.DataFrame, columna: str) -> list[str]:
    """
    Extrae los valores únicos y ordenados de una columna del DataFrame.

    Descarta nulos (``NaN``/``NA``/``NaT``), normaliza a ``str`` con
    ``strip()`` y elimina cadenas vacías.

    Args:
        df: DataFrame fuente.
        columna: Nombre de la columna a extraer.

    Returns:
        Lista ordenada de valores únicos; vacía si la columna no existe
        o no tiene valores utilizables.
    """
    if columna not in df.columns:
        return []
    serie = df[columna].dropna()
    valores: set[str] = set()
    for valor in serie:
        # Un float entero (p.ej. 354.0 al tener la columna nulos) pierde
        # la parte decimal para coincidir con el valor canónico "354".
        if isinstance(valor, float) and valor.is_integer():
            valores.add(str(int(valor)))
        else:
            valores.add(str(valor).strip())
    return sorted(valores - {""})


# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_referencias_factureros(update_trigger: int = 0) -> tuple[list[str], list[str]]:
    """
    Retorna las listas únicas y ordenadas de ``actividad`` y ``partida``
    del padrón de factureros, para poblar los ``selectbox`` de los modales.

    El ``@st.cache_data`` evita re-ejecutar la transformación en cada
    re-render del diálogo; internamente delega en :func:`get_precarizados`
    (que trae su propio caché y fallback a Parquet).

    Args:
        update_trigger: Incrementar para invalidar el caché. Se usa
            ``st.session_state[session_state_update_key]``.

    Returns:
        Tupla ``(actividades, partidas)``; ambas vacías si el padrón
        está vacío.

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    df = get_precarizados(update_trigger=update_trigger)
    return _valores_unicos(df, "actividad"), _valores_unicos(df, "partida")


# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_referencias_honorarios(update_trigger: int = 0) -> list[str]:
    """
    Retorna la lista única y ordenada de ``tipo`` de comprobante de
    la colección ``honorarios``, para poblar el ``selectbox`` de
    ``views.modals.modal_honorarios``.

    Es el equivalente a :func:`get_referencias_factureros` para la
    colección de honorarios: delega en :func:`get_honorarios` (que
    trae su propio caché y fallback a Parquet) y extrae los valores
    únicos con :func:`_valores_unicos`.

    Args:
        update_trigger: Incrementar para invalidar el caché. Se usa
            ``st.session_state["honorarios_dataframes_iteration"]``.

    Returns:
        Lista ordenada de tipos de comprobante; vacía si la
        colección está vacía (el ``selectbox`` del modal queda en
        modo escritura libre).

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    df = get_honorarios(selections=[], update_trigger=update_trigger)
    return _valores_unicos(df, "tipo")


# --------------------------------------------------
@st.cache_data(ttl=3600)
def get_precarizados(
    filtro_avanzado: str = "",
    update_trigger: int = 0,
    cache_file_path: str | None = None,
) -> pd.DataFrame:
    """
    Obtiene el padrón de precarizados desde la API con fallback a un
    caché local en formato Parquet.

    Flujo de prioridad:

        1. Si ``update_trigger == 0``, no hay filtro y existe un caché
           vigente (< 24h), se retorna desde disco.
        2. Si no, se consulta la API.
        3. Si la API falla y existe un caché (cualquier antigüedad), se
           usa como fallback silencioso.
        4. Si la API falla y no hay caché, se re-lanza la excepción.

    El ``@st.cache_data`` (TTL de 1 hora) agrega una capa de caché en
    memoria por encima de la lógica anterior, evitando llamadas repetidas
    a la API dentro del mismo TTL. Las excepciones no se cachean: se
    re-lanzan en cada invocación para que la UI pueda notificarlas.

    Args:
        filtro_avanzado: Filtro dinámico (e.g. ``ejercicio=2024``).
        update_trigger: Incrementar para forzar la actualización de caché.
        cache_file_path: Ruta al archivo Parquet. Si es ``None``, se usa
            la ruta por defecto en ``utils.handling_path.get_cache_path``.

    Returns:
        DataFrame con los precarizados.

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    # Resolver ruta de caché por defecto
    if cache_file_path is None:
        cache_file_path = os.path.join(get_cache_path(), "precarizados_cache.parquet")

    # 1. Intentar leer del caché local si está vigente
    if (
        update_trigger == 0
        and filtro_avanzado == ""
        and cache_file_path
        and os.path.exists(cache_file_path)
    ):
        mtime: datetime = datetime.fromtimestamp(os.path.getmtime(cache_file_path))
        if datetime.now() - mtime < timedelta(hours=24):
            try:
                return pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.warning(
                    "No se pudo leer el caché local (%s): %s",
                    type(read_exc).__name__,
                    read_exc,
                )

    # 2. Consultar la API
    params_peticion: dict[str, Any] = {
        "limit": 0,
        "queryFilter": filtro_avanzado,
    }
    try:
        df: pd.DataFrame = fetch_dataframe(
            Endpoints.SLAVE_FACTUREROS.value, params=params_peticion
        )
    except (ex.APIConnectionError, ex.APIResponseError) as api_exc:
        # 3. Fallback best-effort: usar caché viejo si existe
        if cache_file_path and os.path.exists(cache_file_path):
            try:
                logger.warning("API no disponible, usando caché local: %s", api_exc)
                return pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.error(
                    "No se pudo leer el caché local de fallback: %s",
                    read_exc,
                )
        # 4. Sin fallback: propagar la excepción original
        raise

    # API exitosa - persistir en caché si no hay filtro
    if not df.empty:
        df = df.sort_values(["nombre_completo", "actividad", "partida"], ascending=True)
        if filtro_avanzado == "" and cache_file_path:
            df.to_parquet(cache_file_path)

    return df


@st.cache_data
# --------------------------------------------------
def get_ejercicios_list() -> list[int]:
    return list(range(2010, date.today().year + 1))


# --------------------------------------------------
@st.cache_data(ttl=3600)
def get_honorarios(
    selections: list[tuple[str, list[Any]]],
    filtro_avanzado: str = "",
    update_trigger: int = 0,
    cache_file_path: str | None = None,
) -> pd.DataFrame:
    """
    Obtiene el padrón de honorarios desde la API con fallback a un
    caché local en formato Parquet.

    Flujo de prioridad:

        1. Si ``update_trigger == 0``, no hay filtro y existe un caché
           vigente (< 24h), se retorna desde disco.
        2. Si no, se consulta la API.
        3. Si la API falla y existe un caché (cualquier antigüedad), se
           usa como fallback silencioso.
        4. Si la API falla y no hay caché, se re-lanza la excepción.

    El ``@st.cache_data`` (TTL de 1 hora) agrega una capa de caché en
    memoria por encima de la lógica anterior, evitando llamadas repetidas
    a la API dentro del mismo TTL. Las excepciones no se cachean: se
    re-lanzan en cada invocación para que la UI pueda notificarlas.

    Args:
        filtro_avanzado: Filtro dinámico (e.g. ``ejercicio=2024``).
        update_trigger: Incrementar para forzar la actualización de caché.
        cache_file_path: Ruta al archivo Parquet. Si es ``None``, se usa
            la ruta por defecto en ``utils.handling_path.get_cache_path``.

    Returns:
        DataFrame con los honorarios.

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    # Resolver ruta de caché por defecto
    if cache_file_path is None:
        cache_file_path = os.path.join(get_cache_path(), "honorarios_cache.parquet")

    # 1. Intentar leer del caché local si está vigente
    if (
        update_trigger == 0
        and filtro_avanzado == ""
        and cache_file_path
        and os.path.exists(cache_file_path)
    ):
        mtime: datetime = datetime.fromtimestamp(os.path.getmtime(cache_file_path))
        if datetime.now() - mtime < timedelta(hours=24):
            try:
                return pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.warning(
                    "No se pudo leer el caché local (%s): %s",
                    type(read_exc).__name__,
                    read_exc,
                )

    # 2. Consultar la API
    params_peticion = {
        "limit": 0,
    }
    for nombre_param, valores in selections:
        if valores:
            params_peticion[nombre_param] = ",".join(map(str, valores))

    try:
        df: pd.DataFrame = fetch_dataframe(
            Endpoints.SLAVE_HONORARIOS.value, params=params_peticion
        )
    except (ex.APIConnectionError, ex.APIResponseError) as api_exc:
        # 3. Fallback best-effort: usar caché viejo si existe
        if cache_file_path and os.path.exists(cache_file_path):
            try:
                logger.warning("API no disponible, usando caché local: %s", api_exc)
                return pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.error(
                    "No se pudo leer el caché local de fallback: %s",
                    read_exc,
                )
        # 4. Sin fallback: propagar la excepción original
        raise

    # API exitosa - persistir en caché si no hay filtro
    if not df.empty:
        df = df.sort_values(
            ["ejercicio", "fecha", "nro_comprobante"], ascending=[False, False, True]
        )
        if filtro_avanzado == "" and cache_file_path:
            df.to_parquet(cache_file_path)

    return df
