"""INVICO Slave — Entrypoint principal.

Gestiona el flujo de autenticación (Login) y la navegación MPA
con los módulos de Precarizados, Honorarios y Reportes.
"""

import os
import time

import streamlit as st

from utils.context import clear_token, set_token
from utils.version import get_version
from views.login import render_login

st.set_page_config(
    page_title="INVICO Slave",
    page_icon="⛓️",
    layout="wide",
)

st.markdown(
    """
    <style>
        .stAppDeployButton {
            display: none !important;
        }
    </style>
""",
    unsafe_allow_html=True,
)


# Control de cierre de aplicación
if "app_closing" not in st.session_state:
    st.session_state.app_closing = False

if st.session_state.app_closing:
    st.empty()
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] {display: none;}
        </style>
    """,
        unsafe_allow_html=True,
    )

    st.write("#")
    st.success("### 🔒 Sesión Finalizada")
    st.write("La aplicación de **INVICO Slave** se ha detenido correctamente.")
    st.info("Ya puedes cerrar esta ventana del navegador.")

    time.sleep(1)
    os._exit(0)


# ──────────────────────────────────────────────
# Inicialización del estado de sesión
# ──────────────────────────────────────────────
def initialize_state() -> None:
    """
    Inicializa las claves mínimas en ``session_state`` y sincroniza el
    token con el contexto de servicios.

    El contexto (``utils.context``) es leído por los servicios
    (``services/api_slave.py``) como fallback cuando el caller no les
    pasa el token explícitamente. Esto evita tener que "threading" el
    token a través de cada llamada.
    """
    if "token" not in st.session_state:
        st.session_state["token"] = None
    if "user" not in st.session_state:
        st.session_state["user"] = None

    # Propagar el token de session_state al contexto de servicios
    current_token = st.session_state.get("token")
    if current_token:
        set_token(current_token)
    else:
        clear_token()


# ──────────────────────────────────────────────
# Navegación MPA
# ──────────────────────────────────────────────
def build_navigation() -> None:
    """Construye la navegación con st.navigation y ejecuta la página."""
    user = st.session_state.get("user") or {}
    username = user.get("username", "Usuario")

    pages: list[st.Page] = [
        st.Page(
            "views/precarizados.py",
            title="Precarizados",
            icon="👥",
        ),
        st.Page(
            "views/honorarios.py",
            title="Honorarios",
            icon="💼",
        ),
        st.Page(
            "views/reportes.py",
            title="Reportes (en construcción)",
            icon="📊",
        ),
    ]

    pg = st.navigation(pages)

    # Sidebar: Info de usuario, logout y versión
    with st.sidebar:
        st.divider()

        # Bloque de Usuario y Logout
        cols = st.columns([0.6, 0.4], vertical_alignment="center")
        cols[0].write(f"👤 **{username}**")

        if cols[1].button("Log out", key="logout_btn"):
            st.session_state.app_closing = True
            st.session_state["token"] = None
            st.session_state["user"] = None
            clear_token()  # Limpiar también el contexto de servicios
            st.rerun()

        with st.container():
            st.caption(f"Versión: {get_version()}", text_alignment="center")

    # CSS para optimizar el padding superior
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 1rem !important;
            }
            .stAppHeader {
                background-color: transparent !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pg.run()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    initialize_state()

    # Si el usuario no está autenticado, mostramos la pantalla de login
    if not st.session_state.get("token"):
        render_login()
    else:
        build_navigation()


if __name__ == "__main__":
    main()
