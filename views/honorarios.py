"""
Author: Fernando Corrales <fscpython@gmail.com>
Purpose: ICARO's Home Page
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from components import (
    button_add,
    button_delete,
    button_edit,
    button_export,
    button_selfadd,
    dataframe,
    multiselect_filter,
    text_input_advance_filter,
)
from services import fetch_excel_stream, get_ejercicios_list, get_honorarios
from utils import (
    APIConnectionError,
    APIResponseError,
    Endpoints,
    formato_moneda_ar,
)
from views import dataframe_with_buttons, params_preparation

REPORTE = "honorarios"


# --------------------------------------------------
def dataframe_home_carga(
    df_carga: pd.DataFrame, key: str = "df_home_carga", height: int = 200, **kwargs
):
    with st.container(
        horizontal=False,
        border=True,
        width="stretch",
    ):
        # 1. Creamos una fila de inputs usando columnas (podés elegir cuáles indexar)
        df_filtrado = df_carga.copy()
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            f_id_carga = st.text_input(
                "Id Carga",
                placeholder="Ej: 1175",
                key=f"f_id_carga_{REPORTE}",
            )
        with col2:
            f_cuit = st.text_input(
                "CUIT",
                placeholder="Ej: 20632351514",
                key=f"f_cuit_{REPORTE}",
            )
        with col3:
            f_desc_obra = st.text_input(
                "Descripción Obra",
                placeholder="Ej: Museo",
                key=f"f_desc_obra_{REPORTE}",
            )
        with col4:
            f_actividad = st.text_input(
                "Actividad",
                placeholder="Ej: 11-00-02-79",
                key=f"f_actividad_{REPORTE}",
            )
        with col5:
            f_importe_min = st.number_input(
                "Importe Mínimo",
                min_value=0.0,
                value=0.0,
                step=10000.0,
                key=f"f_importe_min_{REPORTE}",
            )

        # 2. Aplicamos los filtros en cascada sobre el DataFrame (Frontend Puro)
        if f_id_carga:
            df_filtrado = df_filtrado[
                df_filtrado["id_carga"].astype(str).str.contains(f_id_carga, case=False)
            ]
        if f_cuit:
            df_filtrado = df_filtrado[
                df_filtrado["cuit"].astype(str).str.contains(f_cuit, case=False)
            ]
        if f_desc_obra:
            df_filtrado = df_filtrado[
                df_filtrado["desc_obra"]
                .astype(str)
                .str.contains(f_desc_obra, case=False)
            ]
        if f_actividad:
            df_filtrado = df_filtrado[
                df_filtrado["actividad"]
                .astype(str)
                .str.contains(f_actividad, case=False)
            ]
        if f_importe_min:
            df_filtrado = df_filtrado[df_filtrado["importe"] >= f_importe_min]

        event = dataframe(
            df_filtrado,
            key=f"df_carga_{key}",
            height=height,
            on_select="rerun",
            selection_mode="single-row-required",
            column_order=[
                "mes",
                "fecha",
                "id_carga",
                # "nro_comprobante",
                "tipo",
                "fuente",
                "cta_cte",
                "importe",
                "desc_obra",
                # "fondo_reparo",
                "avance",
                "nro_certificado",
                "cuit",
                "origen",
            ],
            column_config={
                "fecha": st.column_config.DateColumn(
                    "fecha",
                    format="DD/MM/YYYY",  # O el formato que prefieras
                ),
                "nro_certificado": st.column_config.TextColumn("cert"),
            },
            **kwargs,
        )
        with st.container(
            horizontal=True,
            border=False,
            width="stretch",
            horizontal_alignment="center",
            gap="medium",
        ):
            if button_selfadd("Autocarga", key=f"btn_selfadd_{key}", type="primary"):
                # Suponiendo que tu archivo se llama pages/autocarga.py o similar
                try:
                    st.switch_page(
                        "src/pages/autocarga/autocarga.py"
                    )  # <--- Esta es la clave
                except Exception as e:
                    st.error(f"No se pudo encontrar la página de autocarga: {e}")
            if button_add("Agregar", key=f"btn_add_{key}"):
                modal_comprobante_gasto(
                    key_prefix=f"add_gasto_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
            if button_edit("Editar", key=f"btn_edit_{key}"):
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    datos_edicion = df_filtrado.iloc[selected_row_index].to_dict()
                    print(datos_edicion)
                    modal_comprobante_gasto(
                        key_prefix=f"edit_gasto_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                        datos_carga=datos_edicion,
                        es_edicion=True,
                    )
            if button_delete("Borrar", key=f"btn_delete_{key}"):
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    form_data = df_filtrado.iloc[selected_row_index].to_dict()
                    # Disparamos el modal de confirmación
                    modal_delete_gasto(
                        id_mongo=str(form_data.get("id")),
                        id_carga_contable=form_data.get("id_carga"),
                        origen=form_data.get("origen", ""),
                        key_prefix=f"delete_carga_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    )

    return event, df_filtrado


# --------------------------------------------------
def render() -> None:

    mis_filtros = [
        {
            "label": "Elija los ejercicios a consultar",
            "options": get_ejercicios_list(),
            "query_param": "ejercicio",
            "key": "ejercicios_" + REPORTE,
            "default": get_ejercicios_list()[-1],
        },
    ]

    honorarios_carga_template(
        key=REPORTE,
        title=REPORTE.capitalize(),
        description="",
        filters_config=mis_filtros,
    )


@st.fragment  # Permite que los filtros internos no recarguen TODA la página
# --------------------------------------------------
def honorarios_carga_template(
    key: str,
    title: str,
    description: str,
    filters_config: list,
):
    """
    Vista reutilizable.
    filters_config: Lista de dicts con ['label', 'options', 'key', 'default']
    """
    st.markdown(f"# {title}")
    st.write(description)

    selections = []

    # 0. Lógica de Exportación
    def download_file():
        # Validamos filtros antes de proceder
        if all(s[1] is not None for s in selections):
            try:
                # Limpiamos basura anterior antes de empezar el proceso pesado
                if f"temp_file_{key}" in st.session_state:
                    del st.session_state[f"temp_file_{key}"]
                with st.spinner("Preparando archivos Excel..."):
                    # Llamada a la API que devuelve StreamingResponse
                    excel_binario = fetch_excel_stream(
                        f"{Endpoints.HONORARIOS_CARGA.value}/export",
                        params_preparation(selections, filtro_avanzado),
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
        for i, f_conf in enumerate(filters_config):
            # Guardamos la selección en un diccionario para la API
            val = multiselect_filter(
                label=f_conf["label"],
                options=f_conf["options"],
                default=f_conf.get("default", []),
                key=f_conf["key"],  # Key única para evitar conflictos en Streamlit
            )
            # El nombre de la clave aquí debe coincidir con lo que espera tu API
            selections.append((f_conf["query_param"], val))

        filtro_avanzado = text_input_advance_filter(
            key="text_input_advance_filter-" + key
        )

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

    # 2. Validar que no haya filtros vacíos
    if any(not s[1] for s in selections):
        st.warning(
            "Seleccione al menos un valor en cada filtro obligatorio. El filtro avanzado es opcional"
        )
        return

    df_carga = pd.DataFrame()
    df_ret = pd.DataFrame()

    # 3. Lógica de Fetch Iterativo (El equivalente al v-for de Vue + API calls)
    try:
        if "carga_dataframes_iteration" not in st.session_state:
            st.session_state["carga_dataframes_iteration"] = 0
        trigger = st.session_state["carga_dataframes_iteration"]
        df_carga, df_ret = get_honorarios(selections, filtro_avanzado, trigger)

        if df_carga.empty:
            st.info("No se encontraron resultados.")
        # else:
        #     st.session_state[f"data_{key}_carga"] = df_final
        #     st.session_state[f"data_{key}_retenciones"] = df_final_ret

    except APIConnectionError as e:
        st.error(f"⚠️ Error de conexión: {e}")
    except APIResponseError as e:
        st.error(f"⚠️ Error de API: {e}")

    # 4. Mostrar resultados (usando session_state para que no desaparezcan)
    if not df_carga.empty:
        df_carga = df_carga.sort_values(
            by=["fecha", "nro_comprobante"], ascending=False
        ).reset_index(drop=True)
        event, df_filtrado = dataframe_home_carga(df_carga, key=f"{key}_df_carga")

        # 2. Lógica de filtrado dinámico
        # Verificamos si hay alguna fila seleccionada
        if len(event.selection.rows) > 0:
            selected_row_index = event.selection.rows[0]
            # Extraemos el id_carga de esa fila
            selected_id = df_filtrado.iloc[selected_row_index]["id_carga"]

            # st.info(f"Mostrando detalles para ID Carga: **{selected_id}**")
            with st.container(horizontal=True, border=False, width="stretch"):
                df_ret_filtrado = df_ret[df_ret["id_carga"] == selected_id]
                df_carga_filtrado = df_filtrado[df_filtrado["id_carga"] == selected_id]
                df_carga_filtrado["importe"] = df_carga_filtrado["importe"].apply(
                    formato_moneda_ar
                )
                dataframe_with_buttons(
                    df_carga_filtrado,
                    key=f"{key}_df_imp",
                    column_order=[
                        "actividad",
                        "partida",
                        "importe",
                    ],
                    show_buttons=False,
                )
                df_ret_filtrado["importe"] = df_ret_filtrado["importe"].apply(
                    formato_moneda_ar
                )
                dataframe_with_buttons(
                    df_ret_filtrado,
                    key=f"{key}_df_ret",
                    column_order=[
                        "codigo",
                        "importe",
                    ],
                    show_buttons=False,
                )


if __name__ == "__main__":
    render()
