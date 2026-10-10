"""
Loader de los 9 CSV públicos de Olist (data/olist/) hacia db/olist.db.

El script es IDEMPOTENTE: por defecto, en cada corrida elimina todas las tablas
y las vuelve a crear antes de cargar los CSV (ver --no-reset para desactivar
este comportamiento).

Orden de carga (respeta las FK, con PRAGMA foreign_keys=ON activo en la conexión):
  sellers, customers, products, product_category_translation, geolocation
  -> orders -> order_items, order_payments, order_reviews

Cuidados aplicados durante la carga (ver también docs/esquema_olist.md):
  - Columnas de ID y de código postal se leen como texto (dtype=str) para no
    perder ceros a la izquierda (ej. "01037").
  - Columnas de fecha se parsean con pandas.to_datetime(errors="coerce"): las
    celdas vacías (pedidos no entregados) quedan como NaT -> se insertan como
    NULL, nunca se inventa una fecha.
  - product_category_name_translation.csv se lee con encoding="utf-8-sig"
    porque su cabecera trae un BOM.
  - geolocation y order_reviews no tienen llave natural única en el CSV (ver
    db/olist_models.py); ninguno de los dos trae columna `id`, así que SQLite
    autoincrementa la PK técnica de esas tablas al insertar.

Uso:
    python seeder/load_olist_csv.py                # carga completa (reset + import)
    python seeder/load_olist_csv.py --no-reset      # agrega datos sin limpiar (no recomendado)
    python seeder/load_olist_csv.py --data-dir otra/ruta
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from db.olist_database import engine
from db.olist_init_db import create_schema, create_views, reset_schema

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "olist"

# (nombre de tabla, archivo CSV, columnas de fecha a parsear, encoding)
_TABLAS = [
    ("sellers", "olist_sellers_dataset.csv", [], "utf-8"),
    ("customers", "olist_customers_dataset.csv", [], "utf-8"),
    ("products", "olist_products_dataset.csv", [], "utf-8"),
    ("product_category_translation", "product_category_name_translation.csv", [], "utf-8-sig"),
    ("geolocation", "olist_geolocation_dataset.csv", [], "utf-8"),
    (
        "orders",
        "olist_orders_dataset.csv",
        [
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        "utf-8",
    ),
    ("order_items", "olist_order_items_dataset.csv", ["shipping_limit_date"], "utf-8"),
    ("order_payments", "olist_order_payments_dataset.csv", [], "utf-8"),
    ("order_reviews", "olist_order_reviews_dataset.csv", ["review_creation_date", "review_answer_timestamp"], "utf-8"),
]

# Columnas que deben leerse como texto (no numéricas) para no perder ceros a
# la izquierda ni que pandas las infiera como float por tener NaN.
_DTYPE_STR = {
    "sellers": ["seller_id", "seller_zip_code_prefix"],
    "customers": ["customer_id", "customer_unique_id", "customer_zip_code_prefix"],
    "products": ["product_id", "product_category_name"],
    "product_category_translation": ["product_category_name", "product_category_name_english"],
    "geolocation": ["geolocation_zip_code_prefix"],
    "orders": ["order_id", "customer_id", "order_status"],
    "order_items": ["order_id", "product_id", "seller_id"],
    "order_payments": ["order_id", "payment_type"],
    "order_reviews": ["review_id", "order_id"],
}

# Columnas numéricas con NULLs en el CSV que pandas infiere como float
# (ej. product_photos_qty=1.0); se convierten a Int64 nullable de pandas antes
# de insertar, para que en SQLite queden como enteros y no como "1.0".
_INT_NULLABLE = {
    "products": [
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
}


def cargar_csv(nombre: str, archivo: str, cols_fecha: list[str], encoding: str, data_dir: Path) -> pd.DataFrame:
    path = data_dir / archivo
    df = pd.read_csv(
        path,
        dtype={c: "string" for c in _DTYPE_STR.get(nombre, [])},
        parse_dates=cols_fecha,
        encoding=encoding,
    )
    for col in _INT_NULLABLE.get(nombre, []):
        df[col] = df[col].astype("Int64")
    return df


def cargar_tabla(conn, nombre: str, df: pd.DataFrame, chunksize: int = 5000) -> int:
    df.to_sql(nombre, conn, if_exists="append", index=False, chunksize=chunksize)
    return len(df)


def main():
    parser = argparse.ArgumentParser(description="Carga los 9 CSV de Olist a db/olist.db.")
    parser.add_argument("--no-reset", action="store_true", help="No limpiar la base de datos antes de cargar (no recomendado)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Carpeta con los 9 CSV de Olist")
    args = parser.parse_args()

    print(f"=== Loader Olist | data-dir={args.data_dir} ===")

    if not args.no_reset:
        print("Limpiando y recreando esquema...")
        reset_schema()
    create_schema()
    create_views()

    conteos_csv: dict[str, int] = {}
    conteos_db: dict[str, int] = {}

    with engine.begin() as conn:
        for nombre, archivo, cols_fecha, encoding in _TABLAS:
            print(f"Cargando {nombre} <- {archivo} ...")
            df = cargar_csv(nombre, archivo, cols_fecha, encoding, args.data_dir)
            conteos_csv[nombre] = len(df)
            n = cargar_tabla(conn, nombre, df)
            print(f"  -> {n:,} filas insertadas")

    print("\n=== Verificación: filas en DB vs. filas leídas del CSV con pandas ===")
    with engine.connect() as conn:
        ok = True
        for nombre, _, _, _ in _TABLAS:
            conteos_db[nombre] = conn.execute(text(f"SELECT COUNT(*) FROM {nombre}")).scalar()
            esperado = conteos_csv[nombre]
            obtenido = conteos_db[nombre]
            estado = "OK" if obtenido == esperado else "¡MISMATCH!"
            if obtenido != esperado:
                ok = False
            print(f"  {nombre:32s} csv={esperado:>8,}  db={obtenido:>8,}  {estado}")

    print("\nCarga completada con éxito." if ok else "\n⚠ Hay tablas con conteos distintos al CSV, revisa el detalle arriba.")


if __name__ == "__main__":
    main()
