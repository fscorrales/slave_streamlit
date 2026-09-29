"""Servicio de fetching de datos para la UI.

Este módulo es **puro**: no importa ``streamlit`` y no aplica cachés de
UI. El decorador ``@st.cache_data`` se aplica en la capa de ``views/``
(véase ``views.precarizados.cached_get_precarizados``).

Mantiene un fallback a caché Parquet local cuando la API no está
disponible (modo degradado).
"""

__all__ = ["get_precarizados"]

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import utils.exceptions as ex
from services.api_slave import fetch_dataframe
from utils.endpoints import Endpoints
from utils.handling_path import get_cache_path

logger = logging.getLogger(__name__)


# --------------------------------------------------
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
