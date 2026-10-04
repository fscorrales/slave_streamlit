"""Modales (``st.dialog``) reutilizables de la capa de vistas."""

import re
import time
from datetime import date, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from components.buttons import button_cancel, button_submit
from services.api_slave import delete_request, post_request, put_request
from services.data_fetcher import (
    get_precarizados,
    get_referencias_factureros,
    get_referencias_honorarios,
)
from services.process_df import (
    construir_payload_honorarios,
    merge_informe_con_precarizados,
    process_informe_por_destino,
)
from utils.context import sync_session_token
from utils.endpoints import Endpoints
from utils.exceptions import AppBaseException


# --- MODAL: ELIMINAR COMPROBANTE GENERICO ---
@st.dialog("Confirmar Eliminación PERMANENTE", width="small")
def modal_delete_registro_gral(
    endpoint: str,
    desc_registro: str,
    session_state_update_key: str = None,
    key_prefix: str = "",
):
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``delete_request`` recibiría ``None`` y
    # lanzaría ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    st.warning(
        f"⚠️ ¿Estás seguro de que deseás eliminar el registro **{desc_registro}**?"
    )
    st.write(
        "Esta acción es permanente y también eliminará todas las retenciones asociadas."
    )

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"):
            st.rerun()

        if button_submit("Si, Eliminar", key=f"{key_prefix}_btn_eliminar"):
            with st.spinner("Eliminando registro..."):
                try:
                    # Pasamos el token explícitamente como defensa adicional
                    # (no dependemos solo del ContextVar, que es frágil).
                    res = delete_request(endpoint, token=token)

                    if res:
                        st.success("Registro eliminado correctamente.")
                        if session_state_update_key:
                            if session_state_update_key not in st.session_state:
                                st.session_state[session_state_update_key] = 0
                            else:
                                st.session_state[session_state_update_key] += 1

                    else:
                        st.error(
                            "Error al eliminar el registro. Por favor, intenta nuevamente."
                        )

                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"Error al eliminar: {e}")


# --------------------------------------------------
def _a_texto(valor: Any) -> str:
    """
    Convierte escalares de ``pandas``/``numpy`` a ``str`` saneado.

    Normaliza ``None``, ``numpy.nan``, ``pd.NA`` y ``pd.NaT`` a cadena
    vacía. Necesario porque ``DataFrame.to_dict()``
    (usado por la grilla para pasar ``datos_carga``) puede traer ``NaN``
    en campos opcionales como ``cuit``, y ``NaN`` no es JSON válido.

    Args:
        valor: Cualquier escalar proveniente de una fila del DataFrame.

    Returns:
        Cadena limpia (vacía si el valor era nulo).
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if pd.isna(valor):  # numpy.nan, pd.NA, pd.NaT
        return ""
    if isinstance(valor, float) and valor.is_integer():
        # Float entero (p.ej. 354.0): pierde la parte decimal para
        # coincidir con el valor canónico "354" de las referencias.
        return str(int(valor))
    return str(valor)


# --- MODAL: AGREGAR / EDITAR FACTURERO (AGENTE) ---
@st.dialog("Agregar / Editar FACTURERO", width="medium")
def modal_precarizado(
    key_prefix: str,
    datos_carga: dict[str, Any] | None = None,
    es_edicion: bool = False,
    es_autocarga: bool = False,
    session_state_update_key: str = "precarizados_uploader_iteration",
) -> None:
    """
    Modal para dar de alta o editar un agente de la colección
    ``factureros`` (padrón de Precarizados).

    Args:
        key_prefix: Prefijo único para las keys de los widgets. Debe
            incluir timestamp con microsegundos para evitar que dos
            aperturas seguidas compartan el estado de los inputs.
        datos_carga: Fila a editar (``df.iloc[i].to_dict()``); ``None``
            en modo alta.
        es_edicion: ``True`` envía ``PUT .../update_one/{id}`` en vez de
            ``POST .../add_one``.
        es_autocarga: ``True`` deshabilita los campos de identidad
            (nombre y CUIT) y solo deja asignar actividad/partida.
        session_state_update_key: Clave de ``st.session_state`` a
            incrementar tras guardar, para refrescar la grilla.
    """
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``post_request``/``put_request`` recibirían
    # ``None`` y lanzarían ``APIConnectionError("No hay token...")``.
    token = sync_session_token(st.session_state.get("token"))

    # pandas NaN/NA/NaT -> None (JSON-compliant; igual que migration/slave.py)
    form_data: dict[str, Any] = {}
    if datos_carga:
        form_data = {
            campo: (None if pd.isna(valor) else valor)
            for campo, valor in datos_carga.items()
        }

    # Referencias del padrón para los selectbox de actividad/partida.
    update_trigger = int(st.session_state.get(session_state_update_key, 0))
    try:
        actividades, partidas = get_referencias_factureros(update_trigger)
    except AppBaseException as exc:
        # No silenciamos: informamos y dejamos los selectbox en modo
        # escritura libre (accept_new_options=True) como fallback.
        st.warning(f"⚠️ No se pudieron cargar las referencias del padrón: {exc}")
        actividades, partidas = [], []

    # En edición, el valor previo debe estar siempre entre las opciones.
    actividad_previa = _a_texto(form_data.get("actividad"))
    partida_previa = _a_texto(form_data.get("partida"))
    if actividad_previa and actividad_previa not in actividades:
        actividades = [actividad_previa, *actividades]
    if partida_previa and partida_previa not in partidas:
        partidas = [partida_previa, *partidas]

    # Estado inicial de los widgets ANTES de crearlos (patrón recomendado
    # por Streamlit: setdefault evita el warning "value + session state").
    st.session_state.setdefault(
        f"{key_prefix}_nombre_completo",
        _a_texto(form_data.get("nombre_completo")),
    )
    st.session_state.setdefault(f"{key_prefix}_cuit", _a_texto(form_data.get("cuit")))
    st.session_state.setdefault(f"{key_prefix}_actividad", actividad_previa or None)
    st.session_state.setdefault(f"{key_prefix}_partida", partida_previa or None)

    # FILA 1: Nombre del Agente (ancho completo)
    nombre_completo = st.text_input(
        "Nombre del Agente",
        key=f"{key_prefix}_nombre_completo",
        disabled=es_autocarga,
        help="Nombre completo del agente tal como figura en el padrón.",
    )

    # FILA 2: CUIT (opcional, ancho completo)
    cuit = st.text_input(
        "CUIT",
        key=f"{key_prefix}_cuit",
        max_chars=11,
        disabled=es_autocarga,
        help="11 dígitos sin guiones. Dejar vacío si el agente no posee CUIT.",
    )

    # FILA 3: Actividad + Partida presupuestaria
    col_actividad, col_partida = st.columns([2, 1])

    # accept_new_options=True: sugiere valores existentes del padrón
    # pero permite cargar actividades/partidas nuevas.
    actividad = col_actividad.selectbox(
        "Actividad",
        options=actividades,
        key=f"{key_prefix}_actividad",
        placeholder="Escriba o elija una Actividad.",
        accept_new_options=True,
        help="Actividad/estructura presupuestaria del agente.",
    )

    partida = col_partida.selectbox(
        "Partida Presupuestaria",
        options=partidas,
        key=f"{key_prefix}_partida",
        placeholder="Escriba o elija una Partida.",
        accept_new_options=True,
    )

    if es_edicion:
        st.caption(
            f"Registro ID: `{form_data.get('id')}` | "
            f"Última actualización: {form_data.get('updated_at') or '—'}"
        )

    st.markdown("---")

    # BOTONES (Cancelar / Agregar o Editar)
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", type="secondary", key=f"{key_prefix}_btn_cancel"):
            st.rerun()  # Cierra el modal de forma segura

        if button_submit(
            "Editar" if es_edicion else "Agregar",
            key=f"{key_prefix}_btn_add",
        ):
            # 1. Validación de datos
            errores: list[str] = []
            nombre_limpio = _a_texto(nombre_completo)
            actividad_limpia = _a_texto(actividad)
            partida_limpia = _a_texto(partida)
            cuit_limpio = _a_texto(cuit)

            if not nombre_limpio:
                errores.append("Debe ingresar el Nombre del Agente.")
            if not actividad_limpia:
                errores.append("Debe indicar la Actividad.")
            if not partida_limpia:
                errores.append("Debe indicar la Partida Presupuestaria.")
            if cuit_limpio and not re.fullmatch(r"\d{11}", cuit_limpio):
                errores.append(
                    "El CUIT debe contener exactamente 11 dígitos (sin guiones)."
                )

            registro_id = _a_texto(form_data.get("id"))
            if es_edicion and not registro_id:
                errores.append("El registro a editar no tiene un ID válido.")

            if errores:
                for err in errores:
                    st.toast(err, icon="⚠️")
            else:
                # 2. Payload ajustado al esquema de la colección
                # ``factureros`` (models.schemas.FactureroReport).
                payload: dict[str, Any] = {
                    "nombre_completo": nombre_limpio,
                    "cuit": cuit_limpio or None,
                    "actividad": actividad_limpia,
                    "partida": partida_limpia,
                    "updated_at": form_data.get(
                        "updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ),
                }

                with st.spinner("Guardando agente..."):
                    # 3. Alta: POST /add_one - Edición: PUT /update_one/{id}
                    # token explícito: el ContextVar no se propaga en diálogos.
                    try:
                        if es_edicion:
                            res = put_request(
                                endpoint=(
                                    f"{Endpoints.SLAVE_FACTUREROS.value}"
                                    f"/update_one/{registro_id}"
                                ),
                                json_body=payload,
                                token=token,
                            )
                        else:
                            res = post_request(
                                endpoint=f"{Endpoints.SLAVE_FACTUREROS.value}/add_one",
                                json_body=payload,
                                token=token,
                            )

                        if res:
                            st.snow()
                            st.toast(
                                f"✅ Agente {nombre_limpio} "
                                f"{'editado' if es_edicion else 'agregado'} con éxito",
                                icon="📈",
                            )

                            # Invalida el caché de la grilla y de las referencias
                            st.session_state[session_state_update_key] = (
                                int(st.session_state.get(session_state_update_key, 0))
                                + 1
                            )
                            time.sleep(2)
                            # Cierra el modal y recarga la página principal
                            st.rerun()
                        else:
                            st.error(
                                "La API no confirmó la operación. "
                                "Verifique e intente nuevamente."
                            )

                    except AppBaseException as exc:
                        st.error(f"⚠️ {exc}")
                    except Exception as exc:
                        st.error(f"❌ Ocurrió un error inesperado: {exc}")


# --- MODAL: AGREGAR COMPROBANTE DE HONORARIOS ---
@st.dialog("Agregar Comprobantes de HONORARIOS", width="large")
def modal_honorarios(
    key_prefix: str,
    session_state_update_key: str = "honorarios_dataframes_iteration",
) -> None:
    """
    Modal para dar de alta un comprobante de honorarios y sus líneas
    en la colección ``slave_honorarios``
    (``POST /slave/honorarios/add_many/{nro_comprobante}``).

    Flujo secuencial **sin tabs**, deliberadamente:

        1. **Paso 1 (gate):** upload del CSV *Resumen de Pagos por
           Destino* -> ``process_informe_por_destino()`` -> merge con
           ``get_precarizados()`` para resolver
           ``cuit``/``actividad``/``partida``.
           Si algún agente no matchea o viene incompleto, el proceso
           **se corta ahí**: el Paso 2 nunca se renderiza, por lo que
           **no se pierde ningún dato** que el usuario hubiera tipeado.
        2. **Paso 2:** fecha, nro de comprobante, cta_cte y tipo.
           De la fecha se derivan ``ejercicio`` y ``mes``; del año,
           los dos últimos dígitos para armar ``"00000/aa"``.
        3. **Paso 3:** confirmación y envío del payload validado
           contra ``HonorarioReport``.

    Se descartó ``st.tabs`` porque las pestañas no se pueden bloquear:
    el usuario podría saltar al Paso 2 sin haber validado el padrón.

    Args:
        key_prefix: Prefijo único para las keys de los widgets (con
            timestamp con microsegundos, igual que ``modal_precarizado``).
        session_state_update_key: Clave de ``st.session_state`` a
            incrementar tras guardar, para refrescar la grilla de
            honorarios (y las referencias de ``tipo``).
    """
    # CRÍTICO: ``@st.dialog`` corre en un contexto de script separado
    # donde los ``ContextVar`` del token NO se heredan.
    token = sync_session_token(st.session_state.get("token"))

    def _barra_cancelar() -> None:
        with st.container(
            horizontal=True, border=False, horizontal_alignment="center", gap="large"
        ):
            if button_cancel(
                "Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"
            ):
                st.rerun()

    # ═══════════════ PASO 1 · INFORME (GATE) ═══════════════
    st.markdown("#### Paso 1 · Informe por Destino")
    st.caption(
        "Cargue el CSV del *Resumen de Pagos por Destino*. El formulario "
        "se habilita únicamente si **todos** los agentes figuran en el "
        "padrón de Precarizados con CUIT, Actividad y Partida."
    )

    uploaded_file = st.file_uploader(
        "Archivo CSV",
        type=["csv"],
        key=f"{key_prefix}_upload_informe",
        help="Exportado del Sistema de Gestión Financiera con título 'Resumen de Pagos por Destino'.",
    )

    if uploaded_file is None:
        st.info("⏳ Cargue el archivo CSV para continuar.")
        _barra_cancelar()
        return

    # ``getvalue()`` no consume el stream: permite re-leer en cada rerun.
    df_informe = process_informe_por_destino(BytesIO(uploaded_file.getvalue()))
    if df_informe.empty:
        st.error(
            "❌ No se pudo interpretar el CSV. Verifique que sea el reporte "
            "'Resumen de Pagos por Destino' y que no esté vacío."
        )
        _barra_cancelar()
        return

    update_trigger = int(st.session_state.get(session_state_update_key, 0))
    try:
        df_precarizados = get_precarizados(update_trigger=update_trigger)
    except AppBaseException as exc:
        st.error(f"⚠️ No se pudo obtener el padrón de Precarizados: {exc}")
        _barra_cancelar()
        return

    df_merged, sin_match, incompletos = merge_informe_con_precarizados(
        df_informe, df_precarizados
    )

    # ── GATE: agentes faltantes => se corta el proceso aquí ──
    if sin_match or incompletos:
        if sin_match:
            st.error(
                f"🚫 **{len(sin_match)} agente(s) NO figuran en el padrón de "
                "Precarizados.** Deben darse de alta antes de continuar:"
            )
            for nombre in sin_match:
                st.markdown(f"- `{nombre}`")
        if incompletos:
            st.error(
                f"🚫 **{len(incompletos)} agente(s) figuran con datos "
                "incompletos** (falta CUIT, Actividad o Partida). Deben "
                "completarse antes de continuar:"
            )
            for nombre in incompletos:
                st.markdown(f"- `{nombre}`")

        st.warning(
            "**El proceso se detiene aquí.** Cancele, cargue esos agentes "
            "desde la vista *Precarizados* y vuelva a intentarlo. Al reabrir "
            "este modal sólo deberá volver a subir el CSV."
        )
        _barra_cancelar()
        return

    st.success(
        f"✅ **{len(df_merged)}** registros leídos · todos con "
        "CUIT / Actividad / Partida resueltos."
    )
    with st.expander("Vista previa de los registros a cargar"):
        st.dataframe(df_merged.head(15), width="stretch")

    # ═══════════════ PASO 2 · DATOS DEL COMPROBANTE ═══════════════
    st.markdown("#### Paso 2 · Datos del Comprobante")

    try:
        tipos, ctas_ctes = get_referencias_honorarios(update_trigger)
    except AppBaseException as exc:
        # No silenciamos: informamos y dejamos el selectbox en modo
        # escritura libre (accept_new_options=True) como fallback.
        st.warning(
            f"⚠️ No se pudieron cargar los tipos de comprobante y/o las cuentas corrientes: {exc}"
        )
        tipos, ctas_ctes = [], []
    col_fecha, col_nro = st.columns(2)
    fecha = col_fecha.date_input(
        "Fecha del comprobante",
        value=date.today(),
        key=f"{key_prefix}_fecha",
        format="DD/MM/YYYY",
    )
    nro_base = col_nro.text_input(
        "Nro. de comprobante",
        key=f"{key_prefix}_nro",
        placeholder="Ej: 123",
        help="Sólo dígitos (hasta 5). Se completa con el año: 00000/aa.",
    )

    col_cta, col_tipo = st.columns(2)
    cta_cte = col_cta.selectbox(
        "Cuenta Corriente",
        options=ctas_ctes,
        key=f"{key_prefix}_cta_cte",
        placeholder="Escriba o elija una Cuenta Corriente.",
        accept_new_options=True,
    )
    tipo = col_tipo.selectbox(
        "Tipo de Comprobante",
        options=tipos,
        key=f"{key_prefix}_tipo",
        placeholder="Escriba o elija un Tipo.",
        accept_new_options=True,
    )

    # ── Datos derivados de la fecha ──
    ejercicio: int = fecha.year
    mes: str = fecha.strftime("%m/%Y")
    nro_limpio: str = nro_base.strip()
    nro_valido: bool = bool(re.fullmatch(r"\d{1,5}", nro_limpio))
    nro_comprobante: str = (
        f"{nro_limpio.zfill(5)}/{str(ejercicio)[-2:]}" if nro_valido else ""
    )
    # selectbox sin selección devuelve None; ``str(None)`` sería
    # "None" (truthy), por eso se normaliza ANTES de validar.
    tipo_limpio: str = "" if tipo is None else str(tipo).strip()

    st.caption(
        f"**Ejercicio:** `{ejercicio}` · **Mes:** `{mes}` · "
        f"**Nro. comprobante:** `{nro_comprobante or '—'}`"
    )

    # ═══════════════ PASO 3 · CONFIRMACIÓN ═══════════════
    st.markdown("#### Paso 3 · Confirmación")
    endpoint: str = (
        f"{Endpoints.SLAVE_HONORARIOS.value}/add_many/"
        f"{quote(nro_comprobante, safe='') if nro_comprobante else '...'}"
    )
    st.caption(f"Se enviarán **{len(df_merged)}** documentos a `{endpoint}`.")

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel(
            "Cancelar", key=f"{key_prefix}_btn_cancel_final", type="secondary"
        ):
            st.rerun()

        if button_submit("Cargar Comprobante", key=f"{key_prefix}_btn_submit"):
            errores: list[str] = []
            if not nro_valido:
                errores.append("El Nro. de comprobante debe tener entre 1 y 5 dígitos.")
            if not fecha:
                errores.append("Debe indicar la Fecha.")
            if not cta_cte.strip():
                errores.append("Debe indicar la Cuenta Corriente.")
            if not tipo_limpio:
                errores.append("Debe indicar el Tipo de comprobante.")

            if errores:
                for err in errores:
                    st.toast(err, icon="⚠️")
                return

            fecha_dt = datetime(fecha.year, fecha.month, fecha.day)

            # Validación estricta contra HonorarioReport: si algo
            # falla, NO se envía nada a la API.
            try:
                registros: list[dict[str, Any]] = construir_payload_honorarios(
                    df_merged,
                    ejercicio=ejercicio,
                    mes=mes,
                    fecha=fecha_dt,
                    nro_comprobante=nro_comprobante,
                    cta_cte=cta_cte.strip(),
                    tipo=tipo_limpio,
                )
            except ValidationError as exc:
                st.error(f"⚠️ Los datos no cumplen el esquema HonorarioReport: {exc}")
                return

            with st.spinner(f"Enviando {len(registros)} documentos..."):
                try:
                    # token explícito: el ContextVar no se propaga en diálogos.
                    res = post_request(endpoint, json_body=registros, token=token)
                except AppBaseException as exc:
                    st.error(f"⚠️ {exc}")
                    return

                if res:
                    st.snow()
                    st.toast(
                        f"✅ Comprobante {nro_comprobante}: "
                        f"+{len(registros)} documentos",
                        icon="📈",
                    )
                    # Invalida el caché de la grilla y de las referencias.
                    st.session_state[session_state_update_key] = (
                        int(st.session_state.get(session_state_update_key, 0)) + 1
                    )
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(
                        "La API no confirmó la operación. "
                        "Verifique e intente nuevamente."
                    )
