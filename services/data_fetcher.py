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
    "sincronizar_caches",
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

# Archivos Parquet del caché en disco (lectura rápida cuando
# ``update_trigger == 0`` y fallback degradado si la API falla).
_PARQUET_PRECARIZADOS: str = "precarizados_cache.parquet"
_PARQUET_HONORARIOS: str = "honorarios_cache.parquet"


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
def get_referencias_honorarios(update_trigger: int = 0) -> tuple[list[str], list[str]]:
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
        Tupla ``(tipos, ctas_ctes)``; ambas vacías si la
        colección está vacía (el ``selectbox`` del modal queda en
        modo escritura libre).

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    df = get_honorarios(selections=[], update_trigger=update_trigger)
    return _valores_unicos(df, "tipo"), _valores_unicos(df, "cta_cte")


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
        cache_file_path = os.path.join(get_cache_path(), _PARQUET_PRECARIZADOS)

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
def _es_fetch_completo(
    selections: list[tuple[str, list[Any]]],
    filtro_avanzado: str,
) -> bool:
    """
    Indica si un fetch de honorarios NO tiene ningún filtro activo.

    Sólo un fetch completo debe escribirse en el Parquet: el archivo
    es el snapshot íntegro que usan la lectura rápida y el fallback;
    guardarlo filtrado lo corrompería (un fetch del ejercicio en curso
    pisaría todos los demás).

    Args:
        selections: Pares ``(parametro, valores)`` de los filtros
            server-side (ej. ``("ejercicio", [2026])``).
        filtro_avanzado: Filtro avanzado Mongo-style (vacío si no hay).

    Returns:
        ``True`` si no hay selections activos ni filtro avanzado.
    """
    if filtro_avanzado:
        return False
    return all(not valores for _, valores in selections)


# --------------------------------------------------
def _filtrar_por_seleccion(
    df: pd.DataFrame,
    selections: list[tuple[str, list[Any]]],
) -> pd.DataFrame | None:
    """
    Aplica ``selections`` a un DataFrame ya cargado (snapshot local).

    Normaliza valores a ``str`` para tolerar diferencias de tipo
    (``2026`` int vs ``"2026"`` str) al comparar contra la columna.

    Args:
        df: DataFrame a filtrar (snapshot del caché en disco).
        selections: Pares ``(parametro, valores)``; los valores vacíos
            se ignoran (sin filtro para ese parámetro).

    Returns:
        El DataFrame filtrado (posiblemente vacío), o ``None`` si algún
        parámetro con valores no corresponde a una columna del
        DataFrame: en ese caso el llamador NO puede resolver el filtro
        localmente y debe consultar a la API.
    """
    mascara: pd.Series = pd.Series(True, index=df.index)
    for nombre_param, valores in selections:
        if not valores:
            continue
        if nombre_param not in df.columns:
            return None
        mascara &= df[nombre_param].astype(str).isin({str(v) for v in valores})
    return df[mascara]


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

    El Parquet es un **snapshot completo**: se escribe SÓLO cuando el
    fetch no tiene ningún filtro activo (:func:`_es_fetch_completo`),
    de modo que un fetch del ejercicio en curso no pise al snapshot a
    los demás.

    Flujo de prioridad:

        1. Si ``update_trigger == 0`` y no hay filtro avanzado, se
           lee el snapshot vigente (< 24h) y se le aplica
           ``selections`` en memoria (:func:`_filtrar_por_seleccion`):
           la vista recibe exactamente lo pedido sin ir a la API. Si
           algún parámetro no es una columna del snapshot, continúa
           a la API.
        2. Si no, se consulta la API.
        3. Si la API falla y existe el snapshot (cualquier antigüedad),
           se usa como fallback aplicándole también ``selections``
           (subconjunto pedido, no el dataset completo).
        4. Si la API falla y no hay caché utilizable, se re-lanza la
           excepción.

    El ``@st.cache_data`` (TTL de 1 hora) agrega una capa de caché en
    memoria por encima de la lógica anterior, evitando llamadas repetidas
    a la API dentro del mismo TTL. Las excepciones no se cachean: se
    re-lanzan en cada invocación para que la UI pueda notificarlas.

    Args:
        selections: Pares ``(parametro, valores)`` de los filtros
            server-side (ej. ``("ejercicio", [2026])``); lista vacía
            o valores vacíos => sin filtro para ese parámetro.
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
        cache_file_path = os.path.join(get_cache_path(), _PARQUET_HONORARIOS)

    # 1. Lectura rápida del snapshot en disco (< 24h). El archivo es
    #    el dataset COMPLETO; aquí se le aplica ``selections`` para
    #    devolver exactamente lo pedido. Si algún parámetro no es una
    #    columna del snapshot no se puede filtrar localmente y se
    #    continúa hacia la API.
    if (
        update_trigger == 0
        and filtro_avanzado == ""
        and cache_file_path
        and os.path.exists(cache_file_path)
    ):
        mtime: datetime = datetime.fromtimestamp(os.path.getmtime(cache_file_path))
        if datetime.now() - mtime < timedelta(hours=24):
            try:
                df_local: pd.DataFrame = pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.warning(
                    "No se pudo leer el caché local (%s): %s",
                    type(read_exc).__name__,
                    read_exc,
                )
            else:
                df_local_filtrado: pd.DataFrame | None = _filtrar_por_seleccion(
                    df_local, selections
                )
                if df_local_filtrado is not None:
                    return df_local_filtrado

    # 2. Consultar la API (``queryFilter`` = filtro avanzado, igual
    # que en get_precarizados; sin esta clave el filtro se ignoraba).
    params_peticion = {
        "limit": 0,
        "queryFilter": filtro_avanzado,
    }
    for nombre_param, valores in selections:
        if valores:
            params_peticion[nombre_param] = ",".join(map(str, valores))

    try:
        df: pd.DataFrame = fetch_dataframe(
            Endpoints.SLAVE_HONORARIOS.value, params=params_peticion
        )
    except (ex.APIConnectionError, ex.APIResponseError) as api_exc:
        # 3. Fallback best-effort: usar el snapshot viejo si existe,
        #    aplicándole también ``selections`` para que el usuario
        #    vea el subconjunto pedido y no el dataset completo.
        if cache_file_path and os.path.exists(cache_file_path):
            try:
                logger.warning("API no disponible, usando caché local: %s", api_exc)
                df_local = pd.read_parquet(cache_file_path)
            except (OSError, ValueError) as read_exc:
                logger.error(
                    "No se pudo leer el caché local de fallback: %s",
                    read_exc,
                )
            else:
                df_local_filtrado = _filtrar_por_seleccion(df_local, selections)
                if df_local_filtrado is not None:
                    return df_local_filtrado
        # 4. Sin fallback utilizable: propagar la excepción original
        raise

    # API exitosa: persistir SÓLO si el fetch fue completo (sin
    # selections activos ni filtro avanzado). El Parquet es un
    # snapshot íntegro; guardarlo filtrado lo corrompería.
    if not df.empty:
        df = df.sort_values(
            ["ejercicio", "fecha", "nro_comprobante"], ascending=[False, False, True]
        )
        if _es_fetch_completo(selections, filtro_avanzado) and cache_file_path:
            df.to_parquet(cache_file_path)

    return df


# --------------------------------------------------
def _mtime_parquet(ruta: str) -> float | None:
    """
    Retorna el ``mtime`` del archivo o ``None`` si no existe.

    Se usa para detectar si una sincronización re-escribió el Parquet
    (API disponible) o si se sirvió el fallback sin actualizar.

    Args:
        ruta: Ruta absoluta al archivo Parquet.

    Returns:
        Segundos desde la época o ``None`` si el archivo no existe.
    """
    try:
        return os.path.getmtime(ruta)
    except OSError:
        return None


# --------------------------------------------------
def sincronizar_caches(
    trigger_precarizados: int = 0,
) -> tuple[dict[str, int], dict[str, str]]:
    """
    Sincronización ligera del caché: memoria + API + Parquet del padrón.

    Pasos:

    1. Limpia el caché en memoria (``st.cache_data`` y
       ``st.cache_resource``): invalida TODAS las funciones con caché,
       incluidas las de honorarios.
    2. Re-consulta el padrón de precarizados a la API con el
       ``update_trigger`` provisto (≠0 salta la lectura del Parquet
       vigente), lo que repuebla la memoria **y reescribe**
       ``precarizados_cache.parquet``.

    **Honorarios NO se descarga aquí**: cada vista sólo necesita el
    ejercicio que está viendo (lo trae ella misma con el trigger ya
    invalidado por el caller) y ``honorarios_cache.parquet`` se
    refresca (o se lee localmente) al cargar la vista de Honorarios
    o al abrir un modal, vía :func:`get_referencias_honorarios`. Así
    el sync no baja decenas de miles de documentos que nadie va a
    mirar.

    El ``trigger_precarizados`` **debe ser > 0**: con ``0``,
    :func:`get_precarizados` leería el Parquet vigente sin consultar
    la API, contrario al propósito de esta función.

    Si la API falla, el Parquet previo **se conserva a propósito** como
    fallback degradado y el recurso queda en ``errores`` informando que
    no se actualizó: nada se silencia.

    Args:
        trigger_precarizados: Valor de
            ``st.session_state[report_data_version_key("precarizados")]``
            ya incrementado. El caller también debe incrementar
            ``honorarios_dataframes_iteration`` para invalidar las
            vistas de honorarios.

    Returns:
        Tupla ``(actualizados, errores)``:

        - ``actualizados``: recurso -> cantidad de registros traídos
          desde la API y persistidos en caché.
        - ``errores``: recurso -> mensaje del fallo. Vacío si todo
          resultó OK.
    """
    # 1) Memoria: purga total (el fetch siguiente la repuebla).
    st.cache_data.clear()
    st.cache_resource.clear()

    actualizados: dict[str, int] = {}
    errores: dict[str, str] = {}

    # ── Precarizados: reescribe precarizados_cache.parquet ──
    ruta_precarizados: str = os.path.join(get_cache_path(), _PARQUET_PRECARIZADOS)
    mtime_previo: float | None = _mtime_parquet(ruta_precarizados)
    try:
        df_precarizados: pd.DataFrame = get_precarizados(
            update_trigger=trigger_precarizados
        )
    except ex.AppBaseException as api_exc:
        errores["Precarizados"] = str(api_exc)
    except Exception as exc:  # p.ej. OSError al escribir el Parquet
        errores["Precarizados"] = f"{type(exc).__name__}: {exc}"
    else:
        sin_cambios: bool = (
            mtime_previo is not None
            and _mtime_parquet(ruta_precarizados) == mtime_previo
        )
        if sin_cambios:
            # El Parquet no se re-escribió: la API falló y se sirvió
            # el fallback, o devolvió datos vacíos.
            errores["Precarizados"] = (
                "el caché Parquet local no fue re-escrito (API vacía "
                "o no disponible); los datos NO se actualizaron."
            )
        else:
            actualizados["Precarizados"] = len(df_precarizados)

    return actualizados, errores
