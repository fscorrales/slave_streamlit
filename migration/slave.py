#!/usr/bin/env python3
"""
Author : Fernando Corrales <fscpython@gmail.com>
Date   : 28-ago-2026
Purpose: Migrate from old Icaro.sqlite to new DB
"""

__all__ = ["SlaveMongoMigrator"]


import json
import os
import re
from pathlib import Path

import pandas as pd
import typer

from migration.migration_client import MigrationClient
from utils import print_rich_table
from utils.endpoints import Endpoints


# --------------------------------------------------
def _normalize_name_for_match(name: object) -> str:
    """
    Normaliza un nombre para hacer matching robusto entre fuentes
    heterogéneas (con/sin coma, con prefijos como ``(JUBILADO)`` o
    ``[LP]``, mayúsculas/minúsculas distintas, etc.).

    La idea es generar una clave estable que permita emparejar
    variaciones del mismo agente sin alterar el nombre original que
    se conserva en el DataFrame.
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
def validate_csv_file(value: Path) -> Path | None:
    """Valida que el valor proporcionado sea una ruta a un archivo CSV existente y legible."""
    if value is None:
        return value

    fixed_path = Path(os.path.normpath(str(value)))

    # 1. Validar existencia del archivo
    if not fixed_path.exists():
        raise typer.BadParameter(
            f"No se pudo encontrar el archivo: '{fixed_path}'.\n"
            "Tip: Intenta poner la ruta entre comillas dobles en la terminal."
        )

    # 2. Validar extensión (.csv)
    if fixed_path.suffix.lower() != ".csv":
        raise typer.BadParameter(
            f"El archivo '{fixed_path.name}' no tiene una extensión válida (.csv)."
        )

    # 3. Validar que el archivo sea legible
    try:
        with open(fixed_path, "r", encoding="utf-8") as f:
            f.read(1)
    except Exception as exc:
        raise typer.BadParameter(
            f"Error al leer el archivo CSV '{fixed_path.name}': {exc}"
        )

    return fixed_path


# --------------------------------------------------
class SlaveMongoMigrator:
    # --------------------------------------------------
    def __init__(self, csv_path: Path, sgf_csv_path: Path | None = None):
        self.csv_path = csv_path
        # Si no se proporciona, asumimos que sgf_proveedores.csv está en el
        # mismo directorio que el CSV principal.
        self.sgf_csv_path = (
            sgf_csv_path
            if sgf_csv_path is not None
            else self.csv_path.parent / "sgf_proveedores.csv"
        )

    # --------------------------------------------------
    def migrate_df_to_mongodb(
        self, table: str, endpoint: str, df: pd.DataFrame
    ) -> None:
        """Migrate DataFrame to MongoDB."""
        # client = MigrationClient(token="token_bypassed")
        client = MigrationClient()
        client.login()
        try:
            records = df.to_dict(orient="records")

            # Sanitizar NaN/NA/NaT -> None para que el resultado sea
            # JSON-compliant. JSON no admite el literal ``NaN`` (que es
            # lo que ``json.dumps`` emite por defecto para
            # ``float('nan')``), por eso lo reemplazamos antes de
            # serializar. En MongoDB los campos nulos se almacenan
            # como ``null``.
            sanitized_records: list[dict[str, object]] = [
                {
                    key: (None if pd.isna(value) else value)
                    for key, value in record.items()
                }
                for record in records
            ]

            # Aplicamos tu FIX directamente aquí
            clean_records = json.loads(
                json.dumps(
                    sanitized_records,
                    default=lambda x: (
                        x.isoformat() if hasattr(x, "isoformat") else str(x)
                    ),
                )
            )

            # El cliente maneja internamente el login y el POST
            result = client.post_batch(endpoint=endpoint, records=clean_records)
            # post_request(endpoint=endpoint, json_body=records, token=token)
            print(f"Successfully migrated {table}'s {len(records)} records to MongoDB.")

        except Exception as e:
            print(f"Error migrar el DataFrame a MongoDB: {e}")

    # --------------------------------------------------
    def migrate_factureros(self):
        """Migrate FACTUREROS table to MongoDB."""
        df = pd.read_csv(self.csv_path, encoding="utf-8")
        table = "PRECARIZADOS"

        # Validación defensiva por si la lectura devolvió un DataFrame vacío
        if df.empty:
            print("⚠️ El archivo está vacío.")
            return

        df.rename(
            columns={
                "Agentes": "nombre_completo",
                "Actividad": "actividad",
                "Partida": "partida",
            },
            inplace=True,
        )

        # ----------------------------------------------------------
        # Enriquecer el DataFrame con el CUIT proveniente de
        # sgf_proveedores.csv. El archivo de proveedores tiene una
        # estructura particular: las primeras 9 columnas son los
        # nombres de los encabezados repetidos en cada fila, y los
        # datos reales comienzan a partir de la columna 9. Por eso
        # se lee con header=None y skiprows=1.
        #
        # Para mejorar el porcentaje de match se utiliza una clave
        # normalizada (sin comas, sin prefijos ``(JUBILADO)`` /
        # ``[LP]``, en mayúsculas y con espacios colapsados) que
        # permite emparejar variaciones del mismo agente.
        # ----------------------------------------------------------
        if not self.sgf_csv_path.exists():
            print(
                f"⚠️ No se encontró el archivo de proveedores SGF en "
                f"'{self.sgf_csv_path}'. Se omite el enriquecimiento con CUIT."
            )
            df["cuit"] = pd.NA
        else:
            df_sgf = pd.read_csv(
                self.sgf_csv_path,
                encoding="latin-1",
                header=None,
                skiprows=1,
            )
            # Seleccionamos Descripción (col 10) y CUIT (col 14) y
            # renombramos para que coincida con la clave de join.
            df_sgf = df_sgf[[10, 14]].copy()
            df_sgf.columns = ["nombre_completo", "cuit"]

            # Construimos una clave de match normalizada y conservamos
            # sólo el primer CUIT por clave para evitar duplicados.
            df_sgf["_match_key"] = df_sgf["nombre_completo"].apply(
                _normalize_name_for_match
            )
            df_sgf = df_sgf.drop_duplicates(subset=["_match_key"])

            df["_match_key"] = df["nombre_completo"].apply(_normalize_name_for_match)

            # Merge left para no perder filas del archivo principal
            # cuando no haya coincidencia en el SGF.
            df = df.merge(df_sgf[["_match_key", "cuit"]], on="_match_key", how="left")
            df = df.drop(columns=["_match_key"])
            # Elimina guiones respetando los nulos (sin hacer .astype(str) a todo el DF)
            df["cuit"] = df["cuit"].str.replace("-", "", regex=False)

        # ----------------------------------------------------------
        # Reporte del porcentaje de agentes con CUIT.
        # ----------------------------------------------------------
        total_agentes: int = len(df)
        agentes_con_cuit: int = int(df["cuit"].notna().sum())
        agentes_sin_cuit: int = total_agentes - agentes_con_cuit
        porcentaje_cuit: float = (
            (agentes_con_cuit / total_agentes) * 100.0 if total_agentes > 0 else 0.0
        )
        print(
            f"📊 Porcentaje de agentes con CUIT: {porcentaje_cuit:.2f}% "
            f"({agentes_con_cuit}/{total_agentes})"
        )
        if agentes_sin_cuit > 0:
            print(
                f"⚠️ {agentes_sin_cuit} agente(s) quedaron sin CUIT y "
                f"se enviarán como null a MongoDB."
            )

        df["partida"] = df["partida"].astype(str)
        df = df.drop_duplicates()
        print_rich_table(df, title=f"Tabla {table} Exportada")

        self.migrate_df_to_mongodb(
            table=table, endpoint=Endpoints.SLAVE_FACTUREROS.value, df=df
        )

    # --------------------------------------------------
    def migrate_honorarios(self):
        """Migrate HONORARIOS Facturareros table to MongoDB."""
        table = "LIQUIDACIONHONORARIOS"
        df = pd.read_csv(self.csv_path, encoding="utf-8")

        # Validación defensiva por si la lectura devolvió un DataFrame vacío
        if df.empty:
            print("⚠️ El archivo está vacío.")
            return

        df.rename(
            columns={
                "Fecha": "fecha",
                "Proveedor": "nombre_completo",
                "Sellos": "sellos",
                "Seguro": "seguro",
                "Tipo": "tipo",
                "Comprobante": "nro_comprobante",
                "MontoBruto": "importe_bruto",
                "IIBB": "iibb",
                "LibramientoPago": "lp",
                "OtraRetencion": "otras_retenciones",
                "Anticipo": "anticipo",
                "Descuento": "descuento",
                "Actividad": "actividad",
                "Partida": "partida",
            },
            inplace=True,
        )

        # df["fecha"] = pd.to_timedelta(df["fecha"], unit="D") + pd.Timestamp(
        #     "1970-01-01"
        # )
        df["ejercicio"] = df["fecha"].dt.year
        df["mes"] = df["fecha"].dt.strftime("%m/%Y")
        df["mutual"] = 0
        df["embargo"] = 0
        keep = ["NoSIIF"]
        df = df.loc[~df.nro_comprobante.str.contains("|".join(keep))]

        # df = df.loc[
        #     :,
        #     [
        #         "ejercicio",
        #         "mes",
        #         "fecha",
        #         "nro_comprobante",
        #         "tipo",
        #         "beneficiario",
        #         "actividad",
        #         "partida",
        #         "importe_bruto",
        #         "iibb",
        #         "lp",
        #         "sellos",
        #         "seguro",
        #         "anticipo",
        #         "descuento",
        #         "mutual",
        #         "embargo",
        #     ],
        # ]

        df["updated_at"] = pd.Timestamp.now()

        ejercicios = df["ejercicio"].unique()
        for ejercicio in ejercicios:
            df_ejercicio = df.loc[df["ejercicio"] == ejercicio]
            self.migrate_df_to_mongodb(
                table=table, endpoint=Endpoints.SLAVE_HONORARIOS.value, df=df_ejercicio
            )

        print_rich_table(df, title=f"Tabla Exportada: {table}")

    # --------------------------------------------------
    def migrate_all(self):
        return_schema = []
        return_schema.append(self.migrate_factureros())
        return_schema.append(self.migrate_honorarios())
        return return_schema


# ──────────────────────────────────────────────
# Inicialización de Typer
# ──────────────────────────────────────────────

app = typer.Typer(
    help="Migrate from Ctas Ctes in XLSX to MongoDB", add_completion=False
)


# --------------------------------------------------
@app.command()
def main(
    file: Path = typer.Option(
        None,
        "--file",
        "-f",
        help="CSV file path",
        exists=False,
        file_okay=True,
        dir_okay=False,
        readable=False,
        callback=validate_csv_file,
    ),
):
    """
    Lee, procesa y escribe el reporte planillometro_hist de Patricia.
    """
    try:
        migrator = SlaveMongoMigrator(
            csv_path=file,
        )
        migrator.migrate_factureros()
        # migrator.migrate_honorarios()
        typer.secho(
            f"[OK] Migracion completada con exito desde {file.name}.",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(
            f"[ERROR] Error durante la ejecucion: {e}", fg=typer.colors.RED, err=True
        )


# --------------------------------------------------
if __name__ == "__main__":
    app()
    # poetry run python -m migration.slave -f "D:\Datos INVICO\IT\slave_streamlit\migration\slave_precarizados.csv"
    # poetry run python -m migration.slave -f "D:\Datos INVICO\IT\slave_streamlit\migration\slave_honorarios.csv"
