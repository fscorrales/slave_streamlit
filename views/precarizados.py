"""Página de Precarizados (Padrón de Factureros)."""

import httpx
import streamlit as st

from services.api_slave import fetch_factureros


def render_precarizados() -> None:
    """Renderiza la vista principal de Precarizados."""
    st.title("👥 Precarizados")
    st.write(
        "Importación CSV y formulario/editor para asignar la estructura presupuestaria por CUIT."
    )

    # TODO: UI para importar CSV y editor por CUIT

    if st.button("Obtener Factureros", key="btn_fetch_factureros"):
        token = st.session_state.get("token")
        try:
            with st.spinner("Consultando factureros..."):
                factureros = fetch_factureros(token=token)
            st.json(factureros)
        except httpx.HTTPStatusError as exc:
            st.error(f"Error HTTP del servidor: {exc.response.status_code} - {exc.response.text}")
        except httpx.RequestError as exc:
            st.error(f"Error de conexión con la API: {exc}")
        except Exception as exc:
            st.error(f"Error inesperado: {exc}")


render_precarizados()
