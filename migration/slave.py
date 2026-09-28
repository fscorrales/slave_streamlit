#!/usr/bin/env python3
"""
Author : Fernando Corrales <fscpython@gmail.com>
Date   : 28-ago-2026
Purpose: Migrate from old Icaro.sqlite to new DB
"""

__all__ = ["SlaveMongoMigrator"]


import json
import os
from pathlib import Path

import pandas as pd
import typer

from migration.migration_client import MigrationClient
from utils.endpoints import Endpoints
from utils import print_rich_table

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
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path

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

            # Aplicamos tu FIX directamente aquí
            clean_records = json.loads(
                json.dumps(
                    records,
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
            print(f"⚠️ El archivo está vacío.")
            return

        df.rename(
            columns={
                "Agentes": "beneficiario",
                "Actividad": "actividad",
                "Partida": "partida",
            },
            inplace=True,
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
            print(f"⚠️ El archivo está vacío.")
            return

        df.rename(
            columns={
                "Fecha": "fecha",
                "Proveedor": "beneficiario",
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
