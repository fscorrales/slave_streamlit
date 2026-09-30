"""Módulo de páginas de la aplicación Streamlit."""

from views.aux_tables import dataframe_with_buttons, report_template
from views.modals import modal_delete_registro_gral, modal_precarizado
from views.precarizados import cached_get_precarizados

__all__ = [
    "report_template",
    "dataframe_with_buttons",
    "cached_get_precarizados",
    "modal_delete_registro_gral",
    "modal_precarizado",
]
