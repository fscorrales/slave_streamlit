"""Módulo de páginas de la aplicación Streamlit."""

from views.aux_tables import dataframe_with_buttons, report_template
from views.modals import modal_delete_registro_gral, modal_precarizado

__all__ = [
    "report_template",
    "dataframe_with_buttons",
    "modal_delete_registro_gral",
    "modal_precarizado",
]
