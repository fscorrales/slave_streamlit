"""
Author: Fernando Corrales <fscpython@gmail.com>
Purpose: Slave's Precarizados Page
"""

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

import utils.exceptions as ex
from services.data_fetcher import get_precarizados
from utils.endpoints import Endpoints
from views import (
    dataframe_with_buttons,
    modal_delete_registro_gral,
    modal_precarizado,
    report_template,
)

REPORTE = "precarizados"


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
        session_state_update_key="precarizados_uploader_iteration",
        key_prefix=f"delete_precarizados_{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )


# --------------------------------------------------
def render() -> None:
    report_template(
        key=REPORTE,
        title=REPORTE.capitalize(),
        description="",
        endpoint=Endpoints.SLAVE_FACTUREROS.value,
        has_export=True,
    )

    # Capturamos el filtro del session_state (que el fragmento actualizó)
    filtro_actual: str = st.session_state.get(f"{REPORTE}_advanced_filter", "")
    trigger: int = st.session_state.get("precarizados_uploader_iteration", 0)

    # Ejecutamos la lógica con el servicio cacheado (@st.cache_data vive
    # en services/data_fetcher.py desde que AGENTS.md §1 lo autorizó)
    df_precarizados = pd.DataFrame()  # type: ignore  # fallback por defecto
    try:
        df_precarizados = get_precarizados(
            filtro_avanzado=filtro_actual, update_trigger=trigger
        )
        if df_precarizados.empty:
            st.info("No se encontraron resultados.")
    except ex.APIConnectionError as exc:
        st.error(f"🌐 {exc}")
    except ex.APIResponseError as exc:
        st.error(f"⚠️ {exc}")

    # Mostrar resultados (usando session_state para que no desaparezcan)
    if not df_precarizados.empty:
        dataframe_with_buttons(
            df_precarizados,
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
