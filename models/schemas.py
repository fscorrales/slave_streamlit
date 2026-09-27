from pydantic import BaseModel
from datetime import datetime


class FactureroReport(BaseModel):
    cuit: str
    nombre: str
    estructura: str


class HonorarioReport(BaseModel):
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
