import httpx
from utils.config import API_BASE_URL


def get_client() -> httpx.Client:
    """Returns a configured HTTPX client."""
    return httpx.Client(base_url=API_BASE_URL, timeout=10.0)


def fetch_factureros() -> dict:
    """
    Fetches the list of factureros from the API.
    Raises httpx.HTTPError if the request fails.
    """
    with get_client() as client:
        try:
            # Assuming the endpoint is /slave/factureros based on the context
            # "endpoints /slave de la API en Koyeb"
            response = client.get("/slave/factureros")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            # Catching and re-raising as per AGENTS.md rules
            raise exc
        except httpx.RequestError as exc:
            raise exc


def fetch_honorarios() -> dict:
    """
    Fetches the list of honorarios from the API.
    Raises httpx.HTTPError if the request fails.
    """
    with get_client() as client:
        try:
            # Assuming the endpoint is /slave/honorarios
            response = client.get("/slave/honorarios")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise exc
        except httpx.RequestError as exc:
            raise exc
