"""Contexto de sesión para propagación implícita entre la UI y los servicios.

Este módulo permite que los servicios lean el token de sesión sin importar
``streamlit`` (cumpliendo el principio de separación de responsabilidades
definido en ``AGENTS.md``) y sin que el caller tenga que pasarlo explícitamente
en cada llamada.

Patrón: la capa de UI (``views/``, ``app.py``) sincroniza el token desde
``st.session_state`` a este contexto en cada rerun del script, y los
servicios (``services/``) lo leen como fallback cuando el caller no lo
provee explícitamente.

Es el equivalente "thread-local" moderno de Python, nativo (``contextvars``)
y libre de dependencias externas.
"""

__all__ = ["set_token", "get_token", "clear_token"]

from contextvars import ContextVar
from typing import Optional

# Token de autenticación de la sesión actual. ``None`` cuando no hay sesión.
_current_token: ContextVar[Optional[str]] = ContextVar(
    "current_token", default=None
)


# --------------------------------------------------
def set_token(token: str) -> None:
    """
    Establece el token de autenticación en el contexto actual.

    Debe llamarse desde la capa de UI (típicamente en ``app.py`` después de
    que ``st.session_state["token"]`` haya sido seteado por ``login.py``).

    Args:
        token: Token JWT de la sesión.
    """
    _current_token.set(token)


# --------------------------------------------------
def get_token() -> Optional[str]:
    """
    Obtiene el token de autenticación del contexto actual.

    Returns:
        Token si está seteado, o ``None`` en caso contrario.
    """
    return _current_token.get()


# --------------------------------------------------
def clear_token() -> None:
    """
    Limpia el token del contexto actual (e.g. al hacer logout).
    """
    _current_token.set(None)
