__all__ = [
    "build_retenciones_payload",
    "formato_moneda_ar",
    "normalize_name_for_match",
]

import re

import pandas as pd


# --------------------------------------------------
def normalize_name_for_match(name: object) -> str:
    """
    Normaliza un nombre para hacer matching robusto entre fuentes
    heterogéneas (con/sin coma, con prefijos como ``(JUBILADO)`` o
    ``[LP]``, mayúsculas/minúsculas distintas, etc.).

    La idea es generar una clave estable que permita emparejar
    variaciones del mismo agente sin alterar el nombre original que
    se conserva en el DataFrame.

    Args:
        name: Nombre crudo (cualquier tipo; ``None``/``NaN`` -> ``""``).

    Returns:
        Clave normalizada en mayúsculas y sin puntuación.
    """
    if pd.isna(name):
        return ""
    text: str = str(name).upper().strip()
    # 1. Quitar prefijos opcionales entre paréntesis o corchetes al inicio.
    text = re.sub(r"^\s*[\(\[][^\)\]]*[\)\]]\s*", "", text)
    # 2. Reemplazar comas y puntos y coma por espacios.
    text = re.sub(r"[,;]", " ", text)
    # 3. Colapsar espacios múltiples.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --------------------------------------------------
def build_retenciones_payload(data: dict) -> dict:
    # Mapeo de campos del objeto a códigos contables de ICARO
    mapeo_codigos = {
        "iibb": "110",
        "sellos": "111",
        "gcias": "113",
        "suss": "114",
        "lp": "112",
        "invico": "337",
    }

    payload_items = []

    for campo, codigo in mapeo_codigos.items():
        # Obtenemos el valor, si no existe o no es numérico usamos 0
        valor = data.get(campo, 0)

        # Filtro: Solo agregamos si es mayor a 0
        if valor > 0:
            payload_items.append(
                {
                    "codigo": codigo,
                    "importe": round(float(valor), 2),  # Aseguramos 2 decimales
                }
            )

    return {"retenciones": payload_items}


# --------------------------------------------------
def formato_moneda_ar(valor):
    # Formato inicial: 1,234.56 -> X para no solapar reemplazos
    return f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
