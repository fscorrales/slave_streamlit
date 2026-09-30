__all__ = [
    "report_template",
    "dataframe_with_buttons",
]

import time
from typing import Any

import pandas as pd
import streamlit as st

from components.buttons import (
    button_add,
    button_delete,
    button_edit,
    button_export,
    button_submit,
)
from components.dataframes import dataframe
from components.text_inputs import text_input_advance_filter
from services.api_slave import fetch_excel_stream, post_request
from utils.context import sync_session_token


# --------------------------------------------------
def params_preparation(
    selections: list[tuple[str, list[Any]]] | None = None,
    filtro_avanzado: str = "",
) -> dict[str, Any]:
    """
    Prepara los parámetros de la API a partir de selecciones y filtro avanzado.

    Args:
        selections: Lista de tuplas ``(nombre_param, valores)`` (e.g. desde
            multiselects). ``valores`` se serializa como string separado por comas.
        filtro_avanzado: Cadena con el filtro dinámico (e.g. ``ejercicio=2024``).

    Returns:
        Diccionario listo para enviar como query params.
    """
    params_peticion: dict[str, Any] = {"limit": 0, "queryFilter": filtro_avanzado}

    if selections:
        for nombre_param, valores in selections:
            if valores:
                params_peticion[nombre_param] = ",".join(map(str, valores))

    return params_peticion


@st.fragment  # Permite que los filtros internos no recarguen TODA la página
# --------------------------------------------------
def report_template(
    key: str,
    title: str,
    endpoint: str,
    description: str,
    has_export: bool = True,
    has_upload: bool = False,
    uploader_func=None,
    uploader_help=None,
):
    """
    Vista reutilizable.
    filters_config: Lista de dicts con ['label', 'options', 'key', 'default']
    """
    # CRÍTICO: Streamlit ejecuta ``@st.fragment`` en un contexto de script
    # separado donde los ``ContextVar`` (token) NO se heredan del script
    # principal. Sin esta sincronización, ``post_request`` (línea más abajo)
    # fallaría con ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    st.markdown(f"# {title}")
    st.write(description)

    # 0. Lógica de Exportación
    def download_file():
        # Validamos filtros antes de proceder
        try:
            # Limpiamos basura anterior antes de empezar el proceso pesado
            if f"temp_file_{key}" in st.session_state:
                del st.session_state[f"temp_file_{key}"]
            with st.spinner("Preparando archivos Excel..."):
                # Llamada a la API que devuelve StreamingResponse
                excel_binario = fetch_excel_stream(
                    f"{endpoint}/export",
                    params_preparation(filtro_avanzado=filtro_avanzado),
                )

                if excel_binario:
                    # IMPORTANTE: Como st.download_button recarga la página,
                    # a veces es mejor usar un link o guardarlo en session_state
                    st.session_state[f"temp_file_{key}"] = excel_binario
                    st.success("✅ Archivo generado con éxito.")
                    st.rerun()

        except Exception as e:
            st.error(f"Error al exportar: {e}")

    # 1. Renderizar Filtros
    # --- Filtros (Estado local del componente) ---
    with st.container(horizontal=True, vertical_alignment="bottom"):
        filtro_avanzado = text_input_advance_filter(
            key="text_input_advance_filter-" + key
        )
        if f"{key}_uploader_iteration" not in st.session_state:
            st.session_state[f"{key}_uploader_iteration"] = 0

        uploaded_file = (
            st.file_uploader(
                f"Cargar CSV de {title}",
                type=["csv"],
                key=f"{key}_upload_file_{st.session_state[f'{key}_uploader_iteration']}",
                label_visibility="visible",
                disabled=not has_upload,  # Add this line to disable the uploader if has_upload is False´
                accept_multiple_files=False,
                help=uploader_help,
            )
            if has_upload
            else None
        )

        if has_export:
            # Aquí podrías integrar tu logic de exportación
            if f"temp_file_{key}" not in st.session_state:
                if button_export("Exportar a Excel", key=f"button_export_{key}"):
                    download_file()
            else:
                # Si hay archivo, el botón "Exportar" desaparece y aparece el de "Descargar"
                st.download_button(
                    label="📥 GUARDAR EXCEL",
                    data=st.session_state[f"temp_file_{key}"],
                    file_name=f"reporte_{key}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"btn_dl_{key}",
                    type="primary",  # Lo ponemos en color para que resalte
                    on_click=lambda: st.session_state.pop(f"temp_file_{key}"),
                )

    if uploaded_file:
        df = read_csv_file(uploaded_file)
        if uploader_func:
            df = uploader_func(df)
        # Validación Visual (El "seguro" del usuario)
        col1, col2, col3 = st.columns(3)
        col1.metric("Filas a procesar", len(df))
        col2.metric("Columnas", len(df.columns))
        col3.info("Validación: OK" if not df.empty else "Error: CSV Vacío o Incorrecto")

        with st.expander("Ver vista previa de datos limpios"):
            st.dataframe(df.head(10), width="stretch")

        if not df.empty:
            with st.container(horizontal=True, horizontal_alignment="center"):
                if button_submit("Confirmar CARGA BD", key=f"btn_add_{key}"):
                    with st.spinner("Ejecutando script de carga..."):
                        # Transformación final para Mongo
                        registros = df.to_dict(orient="records")

                        res = post_request(endpoint, registros, token=token)

                        if res:
                            # 1. Extraer datos principales
                            titulo = res.get("title", "Sincronización")
                            agregados = res.get("added", 0)
                            eliminados = res.get("deleted", 0)
                            lista_errores = res.get("errors", [])
                            num_errores = len(lista_errores)

                            # 2. Toast Combinado (Resumen Ejecutivo)
                            # Ejemplo: 📊 Epam: +160 agregados, -160 eliminados.
                            mensaje_toast = f"📊 {titulo}: +{agregados} agregados, -{eliminados} eliminados."

                            if num_errores > 0:
                                mensaje_toast += f" ({num_errores} con errores)"
                                st.toast(mensaje_toast, icon="⚠️")
                            else:
                                st.toast(mensaje_toast, icon="✅")

                            # 3. Gestión de Errores Detallados (Si existen)
                            if num_errores > 0:
                                with st.expander(
                                    "❌ Detalle de Inconsistencias por Documento",
                                    expanded=True,
                                ):
                                    for error_doc in lista_errores:
                                        doc_id = error_doc.get(
                                            "doc_id", "ID Desconocido"
                                        )
                                        details = error_doc.get("details", [])

                                        st.markdown(f"**Documento ID:** `{doc_id}`")
                                        for det in details:
                                            # Estructura: loc, msg, error_type
                                            st.caption(
                                                f"📍 {det['loc']} | 🏷️ {det['error_type']}"
                                            )
                                            st.write(f"💬 {det['msg']}")
                                        st.divider()
                            else:
                                st.balloons()
                                st.session_state[f"{key}_uploader_iteration"] += 1
                                time.sleep(3)
                                st.rerun()

    # Sincronizamos con el session_state para que 'render' lo vea
    if st.session_state.get(f"{key}_advanced_filter") != filtro_avanzado:
        st.session_state[f"{key}_advanced_filter"] = filtro_avanzado
        st.rerun()  # Forzamos que toda la página (fuera del fragmento) reaccione


# --------------------------------------------------
def dataframe_with_buttons(
    df: pd.DataFrame,
    key: str = "df_with_btns",
    height: int = 150,
    column_order: list = [],
    selection_mode: str = None,
    add_func=None,
    edit_func=None,
    delete_func=None,
    show_buttons: bool = True,
    **kwargs,
):

    with st.container(horizontal=False, border=True, width="stretch"):
        event = dataframe(
            df,
            key=f"{key}",
            height=height,
            column_order=column_order,
            on_select="rerun" if selection_mode else "ignore",
            selection_mode=selection_mode or "multi-row",
        )
        if show_buttons:
            with st.container(
                horizontal=True,
                border=False,
                width="stretch",
                horizontal_alignment="center",
                gap="medium",
            ):
                if button_add(
                    "Agregar",
                    key=f"btn_add_{key}",
                    type="primary",
                    disabled=not add_func,
                ):
                    if add_func:
                        add_func()
                if button_edit("Editar", key=f"btn_edit_{key}", disabled=not edit_func):
                    if edit_func:
                        if len(event.selection.rows) > 0:
                            selected_row_index = event.selection.rows[0]
                            datos_edicion = df.iloc[selected_row_index].to_dict()
                            edit_func(datos_edicion)
                if button_delete(
                    "Borrar", key=f"btn_delete_{key}", disabled=not delete_func
                ):
                    if delete_func:
                        if len(event.selection.rows) > 0:
                            selected_row_index = event.selection.rows[0]
                            datos_eliminar = df.iloc[selected_row_index].to_dict()
                            delete_func(datos_eliminar)
