"""Modales (``st.dialog``) reutilizables de la capa de vistas."""

import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from components.buttons import button_cancel, button_submit
from services.api_slave import delete_request, post_request, put_request
from services.data_fetcher import get_precarizados
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
    return str(valor)


# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def _referencias_factureros(update_trigger: int = 0) -> tuple[list[str], list[str]]:
    """
    Retorna las listas únicas y ordenadas de ``actividad`` y ``partida``
    del padrón de factureros, para poblar los ``selectbox`` del modal.

    Se sirve de ``services.data_fetcher.get_precarizados`` (con su
    fallback a Parquet) envuelto en ``st.cache_data`` para no repetir
    la llamada en cada re-render del diálogo.

    **Por qué vive en ``views/`` y no en ``services/``:** igual que
    ``cached_get_precarizados``, ``@st.cache_data`` es un concepto de
    runtime de Streamlit y ``AGENTS.md`` prohíbe importar ``streamlit``
    en ``services/``/``models/``.

    Args:
        update_trigger: Incrementar para invalidar el caché. Se usa
            ``st.session_state[session_state_update_key]``.

    Returns:
        Tupla ``(actividades, partidas)``; ambas vacías si el padrón
        está vacío.

    Raises:
        APIConnectionError: Propaga desde el servicio si no hay fallback.
        APIResponseError: Propaga desde el servicio si no hay fallback.
    """
    df = get_precarizados(update_trigger=update_trigger)
    if df.empty:
        return [], []
    actividades = sorted({_a_texto(v) for v in df.get("actividad", [])} - {""})
    partidas = sorted({_a_texto(v) for v in df.get("partida", [])} - {""})
    return actividades, partidas


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
        actividades, partidas = _referencias_factureros(update_trigger)
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
                    "updated_at": datetime.now(timezone.utc),
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
