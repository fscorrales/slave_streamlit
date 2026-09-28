"""Página de Carga de Honorarios."""

import httpx
import streamlit as st

from services.api_slave import fetch_honorarios


def render_honorarios() -> None:
    """Renderiza la vista principal de Honorarios."""
    st.title("💼 Carga de Honorarios")
    st.write("Subida de CSV de comprobantes + inputs manuales globales.")

    # TODO: UI para subir CSV y llenar inputs manuales

    if st.button("Ver honorarios actuales", key="btn_fetch_honorarios"):
        try:
            honorarios = fetch_honorarios()
            st.json(honorarios)
        except httpx.HTTPStatusError as exc:
            st.error(f"Error HTTP del servidor: {exc.response.status_code} - {exc.response.text}")
        except httpx.RequestError as exc:
            st.error(f"Error de conexión con la API: {exc}")
        except Exception as exc:
            st.error(f"Error inesperado: {exc}")


render_honorarios()
