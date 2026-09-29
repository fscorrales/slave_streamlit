__all__ = [
    "get_utils_path",
    "get_app_path",
    "get_outside_path",
    "get_cache_path",
    "get_secure_cache_path",
    "get_download_path",
]

import inspect
import os
import sys
from pathlib import Path


# --------------------------------------------------
def get_utils_path() -> str:
    """Retorna la ruta absoluta del directorio ``utils/``."""
    return os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe()))
    )


# --------------------------------------------------
def get_app_path() -> str:
    """
    Retorna la ruta base de la aplicación, soportando modo desarrollo y
    ejecutable empaquetado con PyInstaller.

    En modo desarrollo retorna el directorio padre de ``utils/``.
    En modo empaquetado retorna la carpeta donde reside el ``.exe``.
    """
    if getattr(sys, "frozen", False):
        # Estamos en el .exe: la ruta base es donde está el archivo ejecutable
        return os.path.dirname(sys.executable)
    # Modo desarrollo: subir un nivel desde utils/
    dir_actual: Path = Path(__file__).resolve()
    return str(dir_actual.parent)


# --------------------------------------------------
def get_outside_path() -> str:
    """Retorna el directorio padre de la aplicación."""
    return os.path.dirname(get_app_path())


# --------------------------------------------------
def get_cache_path() -> str:
    """Retorna la ruta de ``.cache`` de la app, creándola si no existe."""
    dir_path: str = os.path.join(get_app_path(), ".cache")
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


# --------------------------------------------------
def get_secure_cache_path() -> str:
    """
    Retorna una ruta de caché en ``%LOCALAPPDATA%\\Slave\\.cache`` (Windows)
    o en el home del usuario (otros OS). Se usa para datos sensibles o
    de gran tamaño que no deben quedar junto al ejecutable.
    """
    app_data: str = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    dir_path: str = os.path.join(app_data, "Slave", ".cache")
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


# --------------------------------------------------
def get_download_path() -> str:
    """Retorna la ruta de la carpeta ``Reportes Descargados``."""
    return os.path.join(get_app_path(), "Reportes Descargados")
