"""
Segunda verificación, independiente de SQLite: recalcula con pandas, leyendo
directamente los CSV originales en data/olist/ (nunca db/olist.db), algunas
de las cifras clave que produce dashboard/queries.py y las compara. Si ambas
vías (CSV+pandas vs SQL sobre olist.db) coinciden, confirma que la base de
datos SQLite refleja fielmente el dataset original y que las consultas de
queries.py están bien construidas.

Métricas recalculadas:
  - clientes únicos con al menos un pedido válido
  - % de clientes recurrentes (más de 1 pedido válido)
  - ingresos de la categoría con más ingresos
  - % de ingresos que concentran las top 5 categorías
  - % de pedidos entregados que llegaron tarde (global)

Uso: python -m dashboard.verify_pandas
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .queries import q01, q03, q08

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "olist"

ESTATUS_INVALIDOS = ("canceled", "unavailable")


def _cargar_csv():
    orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")
    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
    order_items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
    products = pd.read_csv(DATA_DIR / "olist_products_dataset.csv")
    traduccion = pd.read_csv(DATA_DIR / "product_category_name_translation.csv")
    return orders, customers, order_items, products, traduccion


def _pedidos_validos(orders: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    validos = orders[~orders["order_status"].isin(ESTATUS_INVALIDOS)].copy()
    return validos.merge(
        customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left"
    )


def recalcular_con_pandas() -> dict:
    orders, customers, order_items, products, traduccion = _cargar_csv()
    validos = _pedidos_validos(orders, customers)

    # clientes únicos con >= 1 pedido válido
    clientes_unicos = int(validos["customer_unique_id"].nunique())

    # % de clientes recurrentes (> 1 pedido válido)
    pedidos_por_cliente = validos.groupby("customer_unique_id")["order_id"].nunique()
    recurrentes = int((pedidos_por_cliente > 1).sum())
    pct_recurrentes = 100.0 * recurrentes / clientes_unicos if clientes_unicos else 0.0

    # ingresos por categoría (para top e % de las top 5)
    items = order_items.merge(validos[["order_id"]], on="order_id", how="inner")
    items = items.merge(
        products[["product_id", "product_category_name"]], on="product_id", how="left"
    )
    items = items.merge(traduccion, on="product_category_name", how="left")
    items["categoria"] = items["product_category_name_english"].fillna("sin_categoria")
    ingresos_categoria = items.groupby("categoria")["price"].sum().sort_values(ascending=False)
    ingresos_categoria_top = float(ingresos_categoria.iloc[0])
    total_ingresos = float(ingresos_categoria.sum())
    pct_top5_categorias = (
        100.0 * ingresos_categoria.head(5).sum() / total_ingresos if total_ingresos else 0.0
    )

    # % de pedidos entregados que llegaron tarde (global, pedidos válidos)
    entregados = validos[validos["order_delivered_customer_date"].notna()].copy()
    entregados["order_delivered_customer_date"] = pd.to_datetime(
        entregados["order_delivered_customer_date"]
    )
    entregados["order_estimated_delivery_date"] = pd.to_datetime(
        entregados["order_estimated_delivery_date"]
    )
    tardios = entregados["order_delivered_customer_date"] > entregados["order_estimated_delivery_date"]
    pct_tardios = 100.0 * tardios.mean() if len(entregados) else 0.0

    return {
        "clientes_unicos": clientes_unicos,
        "pct_recurrentes": pct_recurrentes,
        "ingresos_categoria_top": ingresos_categoria_top,
        "pct_ingresos_top5_categorias": pct_top5_categorias,
        "pct_pedidos_tardios": pct_tardios,
    }


def _valores_sql() -> dict:
    r1 = q01()
    comparacion = r1["tablas"]["comparacion_recurrentes_vs_no"]
    total_clientes = int(comparacion["clientes"].sum())
    fila_rec = comparacion[comparacion["es_recurrente"] == 1]
    clientes_rec = int(fila_rec["clientes"].iloc[0]) if not fila_rec.empty else 0
    pct_recurrentes = 100.0 * clientes_rec / total_clientes if total_clientes else 0.0

    r3 = q03()
    categorias = r3["tablas"]["pareto_categorias"]
    ingresos_top = float(categorias["ingresos"].iloc[0])
    fila_top5 = categorias[categorias["rango"] == 5]
    pct_top5 = float(fila_top5["pct_acumulado"].iloc[0]) if not fila_top5.empty else float(
        categorias["pct_acumulado"].iloc[-1]
    )

    r8 = q08(min_resenas=1)
    tabla8 = r8["tablas"]["insatisfaccion_por_categoria"]
    pct_tardios = float(tabla8["pct_tardios_global"].iloc[0]) if not tabla8.empty else 0.0

    return {
        "clientes_unicos": total_clientes,
        "pct_recurrentes": pct_recurrentes,
        "ingresos_categoria_top": ingresos_top,
        "pct_ingresos_top5_categorias": pct_top5,
        "pct_pedidos_tardios": pct_tardios,
    }


def _comparar(nombre: str, valor_pandas: float, valor_sql: float, tolerancia: float = 0.5) -> str:
    diff = abs(valor_pandas - valor_sql)
    estado = "OK" if diff <= tolerancia else "DIFF"
    return f"[{estado}] {nombre}: pandas={valor_pandas:,.2f} | sql={valor_sql:,.2f} | diff={diff:,.4f}"


def main() -> None:
    pandas_vals = recalcular_con_pandas()
    sql_vals = _valores_sql()

    print("=== Verificación pandas (CSV) vs SQL (olist.db) ===")
    print(_comparar("Clientes únicos con pedido válido", pandas_vals["clientes_unicos"], sql_vals["clientes_unicos"], tolerancia=0))
    print(_comparar("% clientes recurrentes", pandas_vals["pct_recurrentes"], sql_vals["pct_recurrentes"]))
    print(_comparar("Ingresos categoría top (R$)", pandas_vals["ingresos_categoria_top"], sql_vals["ingresos_categoria_top"]))
    print(_comparar("% ingresos top 5 categorías", pandas_vals["pct_ingresos_top5_categorias"], sql_vals["pct_ingresos_top5_categorias"]))
    print(_comparar("% pedidos tardíos (global)", pandas_vals["pct_pedidos_tardios"], sql_vals["pct_pedidos_tardios"]))


if __name__ == "__main__":
    main()
