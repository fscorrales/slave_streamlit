"""Módulo de páginas de la aplicación Streamlit."""

from views.aux_tables import dataframe_with_buttons, params_preparation, report_template
from views.modals import modal_delete_registro_gral, modal_honorarios, modal_precarizado

__all__ = [
    "report_template",
    "dataframe_with_buttons",
    "params_preparation",
    "modal_delete_registro_gral",
    "modal_honorarios",
    "modal_precarizado",
]
