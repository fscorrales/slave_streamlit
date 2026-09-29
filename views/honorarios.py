"""Página de Carga de Honorarios."""

import streamlit as st

import utils.exceptions as ex
from services.api_slave import fetch_honorarios


def render_honorarios() -> None:
    """Renderiza la vista principal de Honorarios."""
    st.title("💼 Carga de Honorarios")
    st.write("Subida de CSV de comprobantes + inputs manuales globales.")

    # TODO: UI para subir CSV y llenar inputs manuales

    if st.button("Ver honorarios actuales", key="btn_fetch_honorarios"):
        try:
            with st.spinner("Consultando honorarios..."):
                honorarios = fetch_honorarios()
            st.json(honorarios)
        except ex.APIResponseError as exc:
            st.error(f"⚠️ {exc}")
        except ex.APIConnectionError as exc:
            st.error(f"🌐 {exc}")
        except ex.AppBaseException as exc:
            st.error(f"⚠️ {exc}")
        except Exception as exc:
            st.error(f"❌ Error inesperado: {exc}")


render_honorarios()
