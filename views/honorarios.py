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
    dataframe,
    text_filters_bar,
)
from services import (
    get_ejercicios_list,
    get_honorarios,
    get_referencias_honorarios,
)
from services.process_df import apply_text_filters
from utils import (
    APIConnectionError,
    APIResponseError,
    AppBaseException,
    Endpoints,
    build_comprobante_xlsx,
    build_retenciones_payload,
    formato_moneda_ar,
)
from views import (
    ReportState,
    dataframe_with_buttons,
    modal_delete_registro_gral,
    modal_honorarios,
    report_header,
)

REPORTE = "honorarios"

# Filtros particulares de la grilla (frontend puro): se renderizan con
# text_filters_bar() y se aplican en cascada con apply_text_filters()
# sobre el DataFrame ya agrupado, sin volver a tocar la API.
FILTROS_TABLA: list[dict[str, str]] = [
    {"label": "Mes/Año", "column": "mes", "placeholder": "Ej: 01/2026"},
    {
        "label": "Nro Comprobante",
        "column": "nro_comprobante",
        "placeholder": "Ej: 1175",
    },
    {"label": "Tipo", "column": "tipo", "placeholder": "Ej: Honorario"},
]


# --------------------------------------------------
def dataframe_honorarios_comprobantes(
    df_comprobantes: pd.DataFrame,
    key: str = "df_comprobantes",
    height: int = 200,
    **kwargs,
):
    with st.container(
        horizontal=False,
        border=True,
        width="stretch",
    ):
        # 1. Creamos una fila de inputs usando columnas (podés elegir cuáles indexar)
        df_filtrado = (
            df_comprobantes.groupby(
                ["ejercicio", "mes", "fecha", "nro_comprobante", "tipo", "cta_cte"]
            )[["importe_bruto"]]
            .sum()
            .reset_index()
        )
        df_filtrado = df_filtrado.sort_values(
            by=["fecha", "nro_comprobante"], ascending=False
        ).reset_index(drop=True)
        # 2. Filtros particulares (frontend puro, sin llamadas a la API):
        # declarativos en FILTROS_TABLA y aplicados en cascada.
        valores_filtro = text_filters_bar(FILTROS_TABLA, key_prefix=REPORTE)
        df_filtrado = apply_text_filters(df_filtrado, valores_filtro)

        event = dataframe(
            df_filtrado,
            key=f"df_comprobantes_{key}",
            height=height,
            on_select="rerun",
            selection_mode="single-row-required",
            column_order=[
                "ejercicio",
                "mes",
                "fecha",
                "nro_comprobante",
                "tipo",
                "cta_cte",
                "importe_bruto",
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
            if button_add("Agregar", key=f"btn_add_{key}"):
                modal_honorarios(
                    key_prefix=f"add_honorario_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                )
            if button_edit("Editar", key=f"btn_edit_{key}"):
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    datos_edicion = df_filtrado.iloc[selected_row_index].to_dict()
                    # Microsegundos: evita que dos aperturas en el mismo
                    # segundo compartan el estado de los widgets (las keys
                    # derivan del prefijo). Se pasa el df SIN agrupar para
                    # que el modal resuelva los id de cada línea.
                    modal_honorarios(
                        key_prefix=(
                            f"edit_honorario_"
                            f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                        ),
                        datos_carga=datos_edicion,
                        es_edicion=True,
                        df_honorarios=df_comprobantes,
                    )
            if button_delete("Borrar", key=f"btn_delete_{key}"):
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    form_data = df_filtrado.iloc[selected_row_index].to_dict()
                    # Disparamos el modal de confirmación
                    modal_delete_registro_gral(
                        endpoint=f"{Endpoints.SLAVE_HONORARIOS.value}/delete_many/{str(form_data.get('nro_comprobante'))}",
                        desc_registro=str(form_data.get("nro_comprobante")),
                        session_state_update_key="honorarios_dataframes_iteration",
                        key_prefix=f"delete_honorarios_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    )
            if button_export("Generar .xlsx", key=f"btn_export_{key}", type="primary"):
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    main_data = df_filtrado.iloc[selected_row_index].to_dict()
                    selected_id = main_data.get("nro_comprobante")
                    # df_filtrado está agrupado por comprobante y no conserva
                    # las columnas de detalle, por eso se usa el df sin agrupar.
                    df_imp = df_comprobantes[
                        df_comprobantes["nro_comprobante"] == selected_id
                    ]
                    df_imp = (
                        df_imp.groupby(["actividad", "partida"])[["importe_bruto"]]
                        .sum()
                        .reset_index()
                    )
                    df_imp = df_imp.sort_values(
                        by=["actividad", "partida"], ascending=True
                    ).reset_index(drop=True)
                    df_suma = (
                        df_comprobantes[
                            df_comprobantes["nro_comprobante"] == selected_id
                        ][
                            [
                                "iibb",
                                "lp",
                                "sellos",
                                "seguro",
                                "otras_retenciones",
                                "anticipo",
                                "descuento",
                                "mutual",
                                "embargo",
                                "importe_bruto",
                            ]
                        ]
                        .sum()
                        .to_dict()
                    )
                    payload_retenciones = build_retenciones_payload(df_suma)
                    # Extraemos los datos crudos
                    lista_ret = payload_retenciones.get("retenciones", [])
                    # Ordenamos la lista de retenciones por el código (convertido a entero)
                    lista_ordenada = sorted(lista_ret, key=lambda x: int(x["codigo"]))
                    df_ret = pd.DataFrame(lista_ordenada)
                    # Guardamos el .xlsx en session_state: st.download_button
                    # recarga la página y descarta el estado del botón
                    # "Generar", así el archivo queda disponible hasta que se
                    # descargue o cambie la selección.
                    excel_bytes = build_comprobante_xlsx(main_data, df_imp, df_ret)
                    st.session_state[f"temp_file_{key}"] = {
                        "data": excel_bytes,
                        "file_name": f"comprobante_{selected_id}.xlsx",
                        "selected_id": selected_id,
                    }
                    st.success("✅ Archivo generado con éxito. Presione GUARDAR EXCEL.")
                else:
                    st.warning("Seleccione un comprobante antes de generar el archivo.")

            temp_file = st.session_state.get(f"temp_file_{key}")
            if temp_file is not None:
                seleccion_actual = None
                if len(event.selection.rows) > 0:
                    seleccion_actual = df_filtrado.iloc[event.selection.rows[0]][
                        "nro_comprobante"
                    ]
                if (
                    seleccion_actual is None
                    or seleccion_actual == temp_file["selected_id"]
                ):
                    st.download_button(
                        label="📥 GUARDAR EXCEL",
                        data=temp_file["data"],
                        file_name=temp_file["file_name"],
                        mime=(
                            "application/"
                            "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                        key=f"btn_dl_{key}",
                        type="primary",
                        on_click=lambda: st.session_state.pop(f"temp_file_{key}", None),
                    )
                else:
                    # La selección cambió: el archivo generado ya no corresponde.
                    st.session_state.pop(f"temp_file_{key}", None)

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

    # Cabecera compartida (@st.fragment): multiselects server-side +
    # filtro avanzado. Retorna el estado; no hay que leer session_state.
    state: ReportState = report_header(
        key=REPORTE,
        title=REPORTE.capitalize(),
        description="",
        endpoint=Endpoints.SLAVE_HONORARIOS.value,
        filters_config=mis_filtros,
        # El export server-side ({endpoint}/export) de honorarios todavía
        # no está habilitado; la grilla conserva su export propio.
        has_export=False,
    )

    # Validación: los multiselects son obligatorios; el filtro avanzado
    # es opcional.
    if any(not valores for _, valores in state.selections):
        st.warning(
            "Seleccione al menos un valor en cada filtro obligatorio. El filtro avanzado es opcional"
        )
        return

    df_honorarios = pd.DataFrame()

    # Fetch con caché (@st.cache_data en services/data_fetcher.py);
    # honorarios_dataframes_iteration lo incrementan los CRUD al guardar.
    try:
        trigger = int(st.session_state.get("honorarios_dataframes_iteration", 0))
        df_honorarios = get_honorarios(
            selections=state.selections,
            filtro_avanzado=state.filtro_avanzado,
            update_trigger=trigger,
        )

        if df_honorarios.empty:
            st.info("No se encontraron resultados.")

    except APIConnectionError as e:
        st.error(f"⚠️ Error de conexión: {e}")
    except APIResponseError as e:
        st.error(f"⚠️ Error de API: {e}")

    # Mostrar resultados y el detalle del comprobante seleccionado
    if not df_honorarios.empty:
        event, df_filtrado = dataframe_honorarios_comprobantes(
            df_honorarios.copy(), key=f"{REPORTE}_df_comprobantes"
        )

        # Precalienta las referencias del modal de honorarios (tipos
        # y ctas. ctes.) con el mismo trigger. Sin esto, la primera
        # apertura del modal (edición, o alta tras subir el CSV)
        # descarga la colección completa y el diálogo tarda; acá ese
        # costo se paga -una sola vez por trigger- durante la carga
        # de la página y al clicar ya hay caché en memoria.
        try:
            get_referencias_honorarios(update_trigger=trigger)
        except AppBaseException as exc:
            # No corta la página: el modal informa el mismo error y
            # deja los selectbox en escritura libre.
            st.warning(
                f"⚠️ No se pudieron precargar los tipos/cuentas del "
                f"modal de honorarios: {exc}"
            )

        # Lógica de filtrado dinámico sobre la fila seleccionada
        if len(event.selection.rows) > 0:
            selected_row_index = event.selection.rows[0]
            selected_id = df_filtrado.iloc[selected_row_index]["nro_comprobante"]

            with st.container(horizontal=True, border=False, width="stretch"):
                with st.container(horizontal=False, border=True, width="stretch"):
                    df_imp = df_honorarios[
                        df_honorarios["nro_comprobante"] == selected_id
                    ]
                    df_imp = (
                        df_imp.groupby(["actividad", "partida"])[["importe_bruto"]]
                        .sum()
                        .reset_index()
                    )
                    df_imp["importe"] = df_imp["importe_bruto"].apply(formato_moneda_ar)
                    df_imp = df_imp.sort_values(
                        by=["actividad", "partida"], ascending=True
                    ).reset_index(drop=True)
                    dataframe_with_buttons(
                        df_imp,
                        key=f"{REPORTE}_df_imp",
                        column_order=[
                            "actividad",
                            "partida",
                            "importe",
                        ],
                        show_buttons=False,
                    )

                with st.container(horizontal=False, border=True, width="stretch"):
                    df_suma = (
                        df_honorarios[df_honorarios["nro_comprobante"] == selected_id][
                            [
                                "iibb",
                                "lp",
                                "sellos",
                                "seguro",
                                "otras_retenciones",
                                "anticipo",
                                "descuento",
                                "mutual",
                                "embargo",
                                "importe_bruto",
                            ]
                        ]
                        .sum()
                        .to_dict()
                    )
                    payload_retenciones = build_retenciones_payload(df_suma)
                    lista_ret = payload_retenciones.get("retenciones", [])
                    # Ordenamos la lista de retenciones por el código (convertido a entero)
                    lista_ordenada = sorted(lista_ret, key=lambda x: int(x["codigo"]))
                    df_ret = pd.DataFrame(lista_ordenada)
                    # build_retenciones_payload omite importes en 0: sin
                    # retenciones, df_ret queda sin columnas y no hay grilla
                    # que mostrar (evita el KeyError en 'importe').
                    if not df_ret.empty:
                        df_ret["importe"] = df_ret["importe"].apply(formato_moneda_ar)
                        dataframe_with_buttons(
                            df_ret,
                            key=f"{REPORTE}_df_ret",
                            column_order=[
                                "codigo",
                                "importe",
                            ],
                            show_buttons=False,
                        )


if __name__ == "__main__":
    render()
