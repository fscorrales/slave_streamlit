"""Services module."""

from services.api_slave import (
    delete_request,
    fetch_dataframe,
    fetch_excel_stream,
    post_request,
    put_request,
)
from services.data_fetcher import (
    get_ejercicios_list,
    get_honorarios,
    get_precarizados,
    get_referencias_factureros,
)

__all__ = [
    "fetch_dataframe",
    "fetch_excel_stream",
    "post_request",
    "put_request",
    "delete_request",
    "get_precarizados",
    "get_referencias_factureros",
    "get_ejercicios_list",
    "get_honorarios",
]
