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


GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "eval" / "ground_truth_olist.json"


def _categoria_como_vista(items: pd.DataFrame, products: pd.DataFrame, traduccion: pd.DataFrame) -> pd.Series:
    """Igual que vw_ventas_pedido.categoria_ingles: COALESCE(inglés, portugués)."""
    df = items.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
    df = df.merge(traduccion, on="product_category_name", how="left")
    return df["product_category_name_english"].fillna(df["product_category_name"])


def _r2(x) -> float:
    return round(float(x), 2)


def recalcular_oraculo_con_pandas() -> dict[str, list[list]]:
    """Recalcula con pandas, desde los CSV (nunca db/olist.db), el resultado de
    las 10 necesidades del oráculo (eval/ground_truth_olist.json), replicando
    la definición de cada sql_referencia. Devuelve {id: filas}."""
    orders, customers, order_items, products, traduccion = _cargar_csv()
    payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
    reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")
    sellers = pd.read_csv(DATA_DIR / "olist_sellers_dataset.csv")
    for col in ("order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"):
        orders[col] = pd.to_datetime(orders[col])
    validos = _pedidos_validos(orders, customers).merge(
        customers[["customer_id", "customer_state"]], on="customer_id", how="left"
    )
    items = order_items.merge(
        validos[["order_id", "customer_unique_id", "customer_state", "order_purchase_timestamp"]], on="order_id", how="inner"
    )
    items["categoria"] = _categoria_como_vista(items, products, traduccion).values
    calif_pedido = reviews.groupby("order_id")["review_score"].mean()

    out: dict[str, list[list]] = {}

    # n01: % de clientes únicos con más de un pedido válido
    n = validos.groupby("customer_unique_id")["order_id"].nunique()
    out["n01_pct_clientes_recurrentes"] = [[_r2(100 * (n > 1).mean())]]

    # n02: calificación promedio (promedio por pedido) de entregados con retraso / a tiempo
    ent = orders[orders["order_delivered_customer_date"].notna()].copy()
    ent["tarde"] = ent["order_delivered_customer_date"] > ent["order_estimated_delivery_date"]
    ent = ent.join(calif_pedido, on="order_id", how="inner")
    out["n02_calificacion_retraso_vs_a_tiempo"] = [[
        _r2(ent.loc[ent["tarde"], "review_score"].mean()), _r2(ent.loc[~ent["tarde"], "review_score"].mean()),
    ]]

    # n03: % de ingresos que concentran las 5 categorías con más ingresos (incluye el grupo sin categoría en el total)
    ing = items.groupby("categoria", dropna=False)["price"].sum().sort_values(ascending=False)
    out["n03_pct_ingresos_top5_categorias"] = [[_r2(100 * ing.head(5).sum() / ing.sum())]]

    # n04: vendedores con >= 30 pedidos válidos y calificación promedio (por pedido) < 3.5
    ped = items[["seller_id", "order_id"]].drop_duplicates().join(calif_pedido, on="order_id")
    vend = ped.groupby("seller_id").agg(pedidos=("order_id", "size"), calif=("review_score", "mean"))
    out["n04_vendedores_mala_calificacion"] = [[int(((vend["pedidos"] >= 30) & (vend["calif"] < 3.5)).sum())]]

    # n05: estado del cliente con mayor flete/precio
    est = items.groupby("customer_state")[["freight_value", "price"]].sum()
    pct_flete = (100 * est["freight_value"] / est["price"]).sort_values(ascending=False)
    out["n05_estado_mayor_peso_flete"] = [[pct_flete.index[0], _r2(pct_flete.iloc[0])]]

    # n06: método de pago usado en más pedidos válidos (sin not_defined)
    pv = payments.merge(validos[["order_id"]], on="order_id", how="inner")
    pv = pv[pv["payment_type"] != "not_defined"]
    uso = pv.groupby("payment_type")["order_id"].nunique().sort_values(ascending=False)
    out["n06_metodo_pago_mas_usado"] = [[uso.index[0], int(uso.iloc[0])]]

    # n07: mes con más ingresos
    mes = items.groupby(items["order_purchase_timestamp"].dt.strftime("%Y-%m"))["price"].sum().sort_values(ascending=False)
    out["n07_mes_mayores_ingresos"] = [[mes.index[0], _r2(mes.iloc[0])]]

    # n08: categoría (>= 100 reseñas) con mayor % de reseñas de 1 estrella
    cp = items[["order_id"]].copy()
    cp["categoria"] = items.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")         .merge(traduccion, on="product_category_name", how="left")["product_category_name_english"].fillna("sin_categoria").values
    cp = cp.drop_duplicates().merge(reviews[["order_id", "review_score"]], on="order_id", how="inner")
    g = cp.groupby("categoria")["review_score"].agg(resenas="size", unos=lambda s: (s == 1).sum())
    g = g[g["resenas"] >= 100]
    g["pct"] = (100 * g["unos"] / g["resenas"]).round(2)
    g = g.sort_values("pct", ascending=False)
    out["n08_categoria_mas_resenas_1_estrella"] = [[g.index[0], float(g["pct"].iloc[0]), int(g["resenas"].iloc[0])]]

    # n09: top 5 categorías (con nombre, >= 500 pedidos válidos) por % de clientes de compra única
    con_cat = items[items["categoria"].notna()]
    por_cliente = con_cat.groupby(["categoria", "customer_unique_id"])["order_id"].nunique()
    pedidos_cat = con_cat.groupby("categoria")["order_id"].nunique()
    clientes_cat = por_cliente.groupby(level=0).size()
    pct = (por_cliente.eq(1).groupby(level=0).mean() * 100).round(2)
    pct = pct[pedidos_cat.reindex(pct.index) >= 500].sort_values(ascending=False).head(5)
    out["n09_categorias_mas_compra_unica"] = [[c, int(pedidos_cat[c]), int(clientes_cat[c]), float(v)] for c, v in pct.items()]

    # n10: estado (>= 10 vendedores activos) con más clientes únicos por vendedor
    iv = items.merge(sellers[["seller_id", "seller_state"]], on="seller_id", how="inner")
    clientes = iv.groupby("customer_state")["customer_unique_id"].nunique()
    vendedores = iv.groupby("seller_state")["seller_id"].nunique()
    t = pd.DataFrame({"clientes": clientes, "vendedores": vendedores}).dropna()
    t = t[t["vendedores"] >= 10]
    t["cpv"] = (t["clientes"] / t["vendedores"]).round(2)
    t = t.sort_values("cpv", ascending=False)
    out["n10_estado_mas_clientes_por_vendedor"] = [[t.index[0], float(t["cpv"].iloc[0]), int(t["clientes"].iloc[0]), int(t["vendedores"].iloc[0])]]
    return out


def verificar_oraculo() -> list[str]:
    """Compara, para las 10 necesidades, lo recalculado con pandas contra el
    `resultado_esperado` del oráculo, con el mismo árbitro que la evaluación
    (eval/comparador.py) y comparando TODAS las columnas (también las que la
    evaluación no exige)."""
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from eval.comparador import comparar

    gt = {i["id"]: i for i in json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))["preguntas"]}
    lineas = []
    for qid, filas_pandas in recalcular_oraculo_con_pandas().items():
        item = gt[qid]
        esperado = item["resultado_esperado"]
        # todas las columnas: las no evaluadas (null) se comparan como conteo exacto
        tipos = [t or ("texto" if isinstance(v, str) else "conteo") for t, v in zip(item["tipos_columnas"], esperado[0])]
        v = comparar([tuple(f) for f in filas_pandas], [tuple(f) for f in esperado], tipos, item["orden_importa"])
        lineas.append(f"[{'OK' if v.correcto else 'DIFF'}] {qid}: pandas={filas_pandas} | oráculo={esperado}")
    return lineas


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

    print("\n=== Verificación pandas (CSV) vs oráculo (eval/ground_truth_olist.json) ===")
    for linea in verificar_oraculo():
        print(linea)


if __name__ == "__main__":
    main()
