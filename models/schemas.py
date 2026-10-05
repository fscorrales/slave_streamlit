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
    cta_cte: str
    tipo: str
    cuit: str
    nombre_completo: str
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


class InformePorDestino(BaseModel):
    """Modelo de datos para reporte de informes por destino."""

    nombre_completo: str
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


# -------------------------------------------------
class HonorariosUpdate(BaseModel):
    """Payload para actualizar en bloque todos los registros de un comprobante.

    El comprobante a modificar se identifica por el ``nro_comprobante``
    de la **path** de la ruta (el número actual). El
    ``nro_comprobante`` de este schema es el **nuevo** número: si se
    envía, el servidor renombra el comprobante; si es ``None``, lo
    conserva. El ``updated_at`` lo asigna el servidor, por eso no
    forma parte de este schema.
    """

    ejercicio: Optional[int] = None
    mes: Optional[str] = None
    fecha: Optional[datetime] = None
    nro_comprobante: Optional[str] = None
    tipo: str
    cta_cte: Optional[str] = None
    partida: Optional[str] = None
