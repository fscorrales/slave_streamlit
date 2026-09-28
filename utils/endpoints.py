"""Endpoints de la API de INVICO Slave."""

__all__ = ["Endpoints"]

from enum import Enum


# --------------------------------------------------
class Endpoints(str, Enum):
    """URLs de los endpoints disponibles en la API de Koyeb."""

    SLAVE_FACTUREROS = "/slave/factureros"
    SLAVE_HONORARIOS = "/slave/honorarios"
