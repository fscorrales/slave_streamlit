"""
Author: Fernando Corrales <fscpython@gmail.com>
Purpose: Slave's Precarizados Page
"""

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

import utils.exceptions as ex
from components import text_filters_bar
from services.data_fetcher import get_precarizados
from services.process_df import apply_text_filters
from utils.endpoints import Endpoints
from views import (
    ReportState,
    dataframe_with_buttons,
    modal_delete_registro_gral,
    modal_precarizado,
    report_data_version_key,
    report_header,
)

REPORTE = "precarizados"
# Filtros particulares de la grilla (frontend puro): se renderizan con
# text_filters_bar() y se aplican en cascada con apply_text_filters()
# sobre el DataFrame ya obtenido de la API, sin volver a tocar la API.
FILTROS_TABLA: list[dict[str, str]] = [
    {"label": "Nombre", "column": "nombre_completo", "placeholder": "Ej: Juan Pérez"},
    {
        "label": "Actividad",
        "column": "actividad",
        "placeholder": "Ej: 01-00-00-03",
    },
    {"label": "Partida", "column": "partida", "placeholder": "Ej: 344"},
]


# --------------------------------------------------
def add_precarizado() -> None:
    # Microsegundos: evita que dos aperturas en el mismo segundo compartan
    # el estado de los widgets del formulario (las keys derivan del prefijo).
    modal_precarizado(
        key_prefix=f"add_precarizado_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    )


# --------------------------------------------------
def edit_precarizado(datos_edicion: dict[str, Any]) -> None:
    modal_precarizado(
        key_prefix=f"edit_precarizado_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        datos_carga=datos_edicion,
        es_edicion=True,
    )


# --------------------------------------------------
def delete_precarizado(datos_eliminar: dict[str, Any]) -> None:
    modal_delete_registro_gral(
        endpoint=f"{Endpoints.SLAVE_FACTUREROS.value}/delete_one/{datos_eliminar['id']}",
        desc_registro=datos_eliminar["nombre_completo"],
        session_state_update_key=report_data_version_key(REPORTE),
        key_prefix=f"delete_precarizados_{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )


# --------------------------------------------------
def render() -> None:
    # La cabecera (título, filtros, export) es un @st.fragment que retorna
    # el estado del reporte: no hace falta leer nada de session_state.
    state: ReportState = report_header(
        key=REPORTE,
        title=REPORTE.capitalize(),
        description="",
        endpoint=Endpoints.SLAVE_FACTUREROS.value,
        has_export=True,
    )

    # Ejecutamos la lógica con el servicio cacheado (@st.cache_data vive
    # en services/data_fetcher.py desde que AGENTS.md §1 lo autorizó).
    # state.data_version se incrementa al crear/editar/borrar registros
    # y sirve de update_trigger para invalidar ese caché.
    df_precarizados = pd.DataFrame()  # type: ignore  # fallback por defecto
    try:
        df_precarizados = get_precarizados(
            filtro_avanzado=state.filtro_avanzado,
            update_trigger=state.data_version,
        )
        if df_precarizados.empty:
            st.info("No se encontraron resultados.")
    except ex.APIConnectionError as exc:
        st.error(f"🌐 {exc}")
    except ex.APIResponseError as exc:
        st.error(f"⚠️ {exc}")

    # Mostrar resultados (usando session_state para que no desaparezcan)
    if not df_precarizados.empty:
        # Filtros particulares de la grilla (frontend puro, sin llamadas
        # a la API): declarativos en FILTROS_TABLA y aplicados en cascada.
        with st.container(horizontal=False, border=True, width="stretch"):
            valores_filtro = text_filters_bar(FILTROS_TABLA, key_prefix=REPORTE)
            df_vista = apply_text_filters(df_precarizados, valores_filtro)

            dataframe_with_buttons(
                df_vista,
                key=f"{REPORTE}_df_precarizados",
                height=300,
                column_order=["cuit", "nombre_completo", "actividad", "partida"],
                selection_mode="single-row",
                add_func=add_precarizado,
                edit_func=edit_precarizado,
                delete_func=delete_precarizado,
            )


if __name__ == "__main__":
    render()
