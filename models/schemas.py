"""Modelos Pydantic para el sistema INVICO Slave."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Roles de usuario reconocidos por el sistema."""

    ADMIN = "admin"
    USER = "user"
    PENDING = "pending"


class PublicStoredUser(BaseModel):
    """Modelo de usuario devuelto por el backend (/users/me)."""

    id: str
    username: str
    role: Role


class FactureroReport(BaseModel):
    """Modelo de datos para reporte de factureros."""

    cuit: Optional[str] = None
    nombre_completo: str
    actividad: str
    partida: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HonorarioReport(BaseModel):
    """Modelo de datos para reporte de honorarios."""

    ejercicio: int
    mes: str
    fecha: datetime
    nro_comprobante: str
    tipo: str
    cuit: str
    actividad: str
    partida: str
    importe_bruto: float
    # Retenciones
    iibb: float
    lp: float
    sellos: float
    seguro: float
    otras_retenciones: float
    anticipo: float
    descuento: float
    mutual: float
    embargo: float
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
