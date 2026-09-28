"""Servicio para interactuar con los endpoints de Slave en la API de Koyeb."""

import httpx

from utils.config import API_BASE_URL, DEFAULT_TIMEOUT


def get_client(token: str | None = None) -> httpx.Client:
    """Retorna un cliente HTTPX configurado con timeout y token opcional."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API_BASE_URL, headers=headers, timeout=DEFAULT_TIMEOUT)


def fetch_factureros(token: str | None = None) -> dict:
    """
    Obtiene el padrón de factureros desde la API.
    Lanza httpx.HTTPStatusError o httpx.RequestError si la petición falla.
    """
    with get_client(token=token) as client:
        try:
            response = client.get("/slave/factureros")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise exc
        except httpx.RequestError as exc:
            raise exc


def fetch_honorarios(token: str | None = None) -> dict:
    """
    Obtiene el listado de honorarios desde la API.
    Lanza httpx.HTTPStatusError o httpx.RequestError si la petición falla.
    """
    with get_client(token=token) as client:
        try:
            response = client.get("/slave/honorarios")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise exc
        except httpx.RequestError as exc:
            raise exc
