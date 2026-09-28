import time
from typing import Any, Dict

import httpx

from utils.config import settings

# --------------------------------------------------
class MigrationClient:
    # --------------------------------------------------
    def __init__(self, username: str = None, password: str = None, token: str = None):
        self.base_url = settings.BASE_URL
        self.token = token
        self.username = username or settings.ADMIN_USERNAME
        self.password = password or settings.ADMIN_PASSWORD
        self.client = httpx.Client(
            timeout=settings.DEFAULT_TIMEOUT
        )  # Timeout extendido para procesos batch

    # --------------------------------------------------
    def login(self) -> str:
        """Autenticación usando x-www-form-urlencoded."""
        url = f"{self.base_url}/auth/login"
        data = {"username": self.username, "password": self.password}

        response = self.client.post(url, data=data)
        response.raise_for_status()

        self.token = response.json().get("access_token")
        return self.token

    # --------------------------------------------------
    def post_batch(
        self, endpoint: str, records: list[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Envía los registros a la API de Koyeb."""
        if not self.token:
            self.login()

        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            response = self.client.post(url, json=records, headers=headers)

            # Manejo específico de Koyeb (503 / 502)
            if response.status_code in [502, 503]:
                print("[WAIT] Servidor despertando en Koyeb... reintentando en 10s.")
                time.sleep(10)
                return self.post_batch(endpoint, records)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            print(f"[ERROR] Error de API: {e.response.text}")
            raise
