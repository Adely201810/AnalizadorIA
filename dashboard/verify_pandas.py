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
    products = products.copy()
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

    # n04 (criterio completo, D-20): vendedores con >= 30 pedidos válidos, en el 25 % con más
    # ingresos (CUME_DIST <= 0.25) y con calificación promedio por pedido < 3.5 o > 15 % de
    # sus pedidos entregados con retraso.
    fechas = orders[["order_id", "order_delivered_customer_date", "order_estimated_delivery_date"]]
    ped = items[["seller_id", "order_id"]].drop_duplicates().merge(fechas, on="order_id", how="left")
    ped = ped.join(calif_pedido, on="order_id")
    ped["entregado"] = ped["order_delivered_customer_date"].notna()
    ped["tarde"] = ped["entregado"] & (ped["order_delivered_customer_date"] > ped["order_estimated_delivery_date"])
    vend = ped.groupby("seller_id").agg(pedidos=("order_id", "size"), calif=("review_score", "mean"),
                                        tardes=("tarde", "sum"), entregados=("entregado", "sum"))
    vend["pct_tardias"] = 100 * vend["tardes"] / vend["entregados"].where(vend["entregados"] > 0)
    vend["ingresos"] = items.groupby("seller_id")["price"].sum()
    eleg = vend[vend["pedidos"] >= 30].copy()
    eleg["cd"] = eleg["ingresos"].rank(ascending=False, method="max") / len(eleg)  # = CUME_DIST() OVER (ORDER BY ingresos DESC)
    out["n04_vendedores_problematicos"] = [[int(((eleg["cd"] <= 0.25) & ((eleg["calif"] < 3.5) | (eleg["pct_tardias"] > 15))).sum())]]

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
    out.update(_recalcular_preguntas_nuevas(orders, customers, products, traduccion, payments, reviews, sellers,
                                            validos, items, calif_pedido))
    out.update(_recalcular_prueba_2(orders, products, traduccion, payments, reviews, sellers, validos, items))
    return out


def _recalcular_prueba_2(orders, products, traduccion, payments, reviews, sellers, validos, items) -> dict[str, list[list]]:
    """Etapa 3, Paso 2: las 20 preguntas de PRUEBA_2 (p2_01-p2_20), replicando la definición
    de cada una desde los CSV (sin olist.db)."""
    out: dict[str, list[list]] = {}
    dias = lambda a, b: (a - b).dt.total_seconds() / 86400  # = julianday(a) - julianday(b)
    ent = validos[validos["order_delivered_customer_date"].notna()]

    out["p2_01_vendedores_rio"] = [[int((sellers["seller_city"] == "rio de janeiro").sum())]]
    out["p2_02_pagos_debito"] = [[int((payments["payment_type"] == "debit_card").sum())]]
    out["p2_03_productos_mas_10kg"] = [[int((products["product_weight_g"] > 10000).sum())]]
    out["p2_04_resenas_con_mensaje"] = [[int(reviews["review_comment_message"].notna().sum())]]
    rapido = dias(ent["order_delivered_customer_date"], ent["order_purchase_timestamp"]) <= 7
    out["p2_05_pct_entrega_7_dias"] = [[_r2(100 * rapido.mean())]]
    con_ventas = set(items["seller_id"])
    out["p2_06_pct_vendedores_sin_ventas"] = [[_r2(100 * (~sellers["seller_id"].isin(con_ventas)).mean())]]
    iv = items.merge(sellers[["seller_id", "seller_state"]], on="seller_id")
    out["p2_07_pct_ingresos_vendedores_mg"] = [[_r2(100 * iv.loc[iv["seller_state"] == "MG", "price"].sum() / iv["price"].sum())]]
    con_titulo = reviews[reviews["review_comment_title"].notna()]
    out["p2_08_pct_resenas_titulo_bajas"] = [[_r2(100 * (con_titulo["review_score"] <= 2).mean())]]
    out["p2_09_pct_articulos_flete_mayor_precio"] = [[_r2(100 * (items["freight_value"] > items["price"]).mean())]]
    out["p2_10_pedidos_validos_2017"] = [[int((validos["order_purchase_timestamp"].dt.year == 2017).sum())]]
    pv = payments[payments["order_id"].isin(validos["order_id"])]
    out["p2_11_ticket_promedio"] = [[_r2(pv.groupby("order_id")["payment_value"].sum().mean())]]
    nov = items[items["order_purchase_timestamp"].dt.strftime("%Y-%m") == "2017-11"]
    out["p2_12_precio_promedio_nov_2017"] = [[_r2(nov["price"].mean())]]
    out["p2_13_articulos_clientes_rs"] = [[int((items["customer_state"] == "RS").sum())]]
    cat = items.merge(products[["product_id", "product_category_name"]], on="product_id") \
        .merge(traduccion, on="product_category_name", how="left")
    cuenta = cat["product_category_name_english"].fillna("sin_categoria").value_counts()
    out["p2_14_categoria_mas_articulos"] = [[cuenta.index[0], int(cuenta.iloc[0])]]
    est = sellers["seller_state"].value_counts()
    out["p2_15_top3_estados_vendedores"] = [[e, int(n)] for e, n in est.head(3).items()]
    dia = ((validos["order_purchase_timestamp"].dt.dayofweek + 1) % 7).value_counts()  # pandas: lunes=0; SQL %w: domingo=0
    out["p2_16_dia_semana_mas_pedidos"] = [[int(dia.index[0]), int(dia.iloc[0])]]
    npc = validos.groupby("customer_unique_id")["order_id"].nunique()
    pago_pedido = payments.groupby("order_id")["payment_value"].sum()
    v2 = validos[validos["customer_unique_id"].isin(npc[npc >= 2].index)]
    gasto = v2.assign(p=v2["order_id"].map(pago_pedido).fillna(0)).groupby("customer_unique_id")["p"].sum()
    out["p2_17_gasto_clientes_2_pedidos"] = [[_r2(gasto.mean())]]
    flete = _flete_por_pedido_todos(items, validos)
    d = ent.assign(dias=dias(ent["order_delivered_customer_date"], ent["order_purchase_timestamp"]))
    d = d.merge(flete.rename("fl"), left_on="order_id", right_index=True, how="inner")
    out["p2_18_dias_entrega_por_flete"] = [[_r2(d.loc[d["fl"] > 50, "dias"].mean()), _r2(d.loc[d["fl"] <= 50, "dias"].mean())]]
    art = items.groupby("seller_id").size()
    grandes = art[art >= 50].index
    calif = reviews.groupby("order_id")["review_score"].mean()
    sp = items.loc[items["seller_id"].isin(grandes), ["seller_id", "order_id"]].drop_duplicates()
    sp = sp.merge(calif.rename("s"), left_on="order_id", right_index=True, how="inner")
    mejor = sp.groupby("seller_id")["s"].mean().sort_values(ascending=False)
    out["p2_19_vendedor_mejor_calificado"] = [[mejor.index[0], _r2(mejor.iloc[0])]]
    pp = pv.groupby("order_id").agg(t=("payment_value", "sum"), m=("payment_type", "nunique"))
    out["p2_20_pct_pagado_varios_metodos"] = [[_r2(100 * pp.loc[pp["m"] > 1, "t"].sum() / pp["t"].sum())]]
    return out


def _flete_por_pedido_todos(items_validos, validos) -> pd.Series:
    """Flete total por pedido sumando TODOS sus artículos (la referencia de p2_18 no filtra
    order_items por estatus; para pedidos válidos es lo mismo que sumar los artículos válidos)."""
    return items_validos.groupby("order_id")["freight_value"].sum()


def _recalcular_preguntas_nuevas(orders, customers, products, traduccion, payments, reviews, sellers,
                                 validos, items, calif_pedido) -> dict[str, list[list]]:
    """Las 20 preguntas nuevas del oráculo v3 (x01-x20), replicando cada sql_referencia."""
    out: dict[str, list[list]] = {}
    dias = lambda a, b: (a - b).dt.total_seconds() / 86400  # = julianday(a) - julianday(b)
    con_cat = items.merge(products[["product_id", "product_category_name", "product_weight_g"]], on="product_id") \
        .merge(traduccion, on="product_category_name", how="inner")  # JOIN (no LEFT) a la traducción
    ent = validos[validos["order_delivered_customer_date"].notna()]

    out["x01_pedidos_cancelados"] = [[int((orders["order_status"] == "canceled").sum())]]
    tarde = ent["order_delivered_customer_date"] > ent["order_estimated_delivery_date"]
    out["x02_pct_entregas_con_retraso"] = [[_r2(100 * tarde.mean())]]
    out["x03_flete_promedio_por_articulo"] = [[_r2(items["freight_value"].mean())]]
    out["x04_pct_resenas_5_estrellas"] = [[_r2(100 * (reviews["review_score"] == 5).mean())]]
    ing = items.groupby("seller_id")["price"].sum().sort_values(ascending=False)
    out["x05_vendedor_mas_ingresos"] = [[ing.index[0], _r2(ing.iloc[0])]]
    art = items.groupby("order_id").size()
    out["x06_pct_pedidos_varios_articulos"] = [[_r2(100 * (art > 1).mean())]]
    peds = con_cat.loc[con_cat["product_category_name_english"] == "bed_bath_table", "order_id"].drop_duplicates()
    out["x07_calificacion_pedidos_bed_bath_table"] = [[_r2(calif_pedido.reindex(peds).dropna().mean())]]
    rj = ent[ent["customer_state"] == "RJ"]
    out["x08_dias_entrega_rj"] = [[_r2(dias(rj["order_delivered_customer_date"], rj["order_purchase_timestamp"]).mean())]]
    canc = orders[orders["order_status"] == "canceled"]
    mes = canc["order_purchase_timestamp"].dt.strftime("%Y-%m").value_counts()
    out["x09_mes_mas_cancelados"] = [[mes.index[0], int(mes.iloc[0])]]
    g = con_cat.groupby("product_category_name_english")["price"].agg(["count", "mean"])
    g = g[g["count"] >= 200].sort_values("mean", ascending=False)
    out["x10_categoria_precio_promedio_mas_alto"] = [[g.index[0], _r2(g["mean"].iloc[0])]]
    out["x11_clientes_unicos_sp"] = [[int(validos.loc[validos["customer_state"] == "SP", "customer_unique_id"].nunique())]]
    out["x12_vendedores_health_beauty"] = [[int(con_cat.loc[con_cat["product_category_name_english"] == "health_beauty", "seller_id"].nunique())]]
    tot = (items["price"] + items["freight_value"]).groupby([items["customer_state"], items["order_id"]]).sum()
    est = tot.groupby(level=0).agg(["count", "mean"])
    est = est[est["count"] >= 1000].sort_values("mean", ascending=False)
    out["x13_estado_mayor_gasto_promedio"] = [[est.index[0], _r2(est["mean"].iloc[0])]]
    iv = items.merge(sellers[["seller_id", "seller_state"]], on="seller_id", how="inner")
    out["x14_ingresos_vendedores_sp_fuera_sp"] = [[_r2(iv.loc[(iv["seller_state"] == "SP") & (iv["customer_state"] != "SP"), "price"].sum())]]
    boleto = payments.merge(validos[["order_id"]], on="order_id")
    boleto = set(boleto.loc[boleto["payment_type"] == "boleto", "order_id"])
    out["x15_calificacion_pedidos_boleto"] = [[_r2(reviews.loc[reviews["order_id"].isin(boleto), "review_score"].mean())]]
    out["x16_pct_productos_sin_categoria"] = [[_r2(100 * products["product_category_name"].isna().mean())]]
    ciu = iv.merge(sellers[["seller_id", "seller_city"]], on="seller_id").groupby("seller_city")["order_id"].nunique() \
        .sort_values(ascending=False)
    out["x17_top2_ciudades_vendedores"] = [[c, int(n)] for c, n in ciu.head(2).items()]
    peso = con_cat.loc[con_cat["product_category_name_english"] == "furniture_decor", "product_weight_g"]
    out["x18_peso_promedio_furniture_decor"] = [[_r2(peso.astype("float").mean())]]
    anio = items.groupby(items["order_purchase_timestamp"].dt.strftime("%Y"))["price"].sum().sort_values(ascending=False)
    out["x19_anio_mas_ingresos"] = [[anio.index[0], _r2(anio.iloc[0])]]
    cli = validos[["customer_unique_id", "order_id"]].drop_duplicates()
    unos = set(reviews.loc[reviews["review_score"] == 1, "order_id"])
    con_uno = cli.loc[cli["order_id"].isin(unos), "customer_unique_id"].nunique()
    out["x20_pct_clientes_resena_1_estrella"] = [[_r2(100 * con_uno / cli["customer_unique_id"].nunique())]]
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
    recalculado = recalcular_oraculo_con_pandas()
    for qid in sorted(set(gt) - set(recalculado)):
        lineas.append(f"[DIFF] {qid}: sin recálculo con pandas")
    for qid, filas_pandas in recalculado.items():
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


def verificar_q01_tablas(min_clientes_categoria: int = 200) -> list[str]:
    """Etapa 2, Paso 4: las 4 tablas de q01 recalculadas desde los CSV, independientemente
    de olist.db (q01 se reescribió para no recalcular CTEs). Los empates se comparan
    ordenando también por la clave, porque su orden no es parte del resultado."""
    orders, customers, order_items, products, traduccion = _cargar_csv()
    pagos = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
    resenas = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")
    validos = orders[~orders["order_status"].isin(ESTATUS_INVALIDOS)].merge(
        customers[["customer_id", "customer_unique_id", "customer_state"]], on="customer_id")

    num = validos.groupby("customer_unique_id")["order_id"].nunique()
    rc = pd.DataFrame({"customer_unique_id": num.index, "es_recurrente": (num > 1).astype(int).values})
    pago_pedido = pagos.groupby("order_id")["payment_value"].sum()
    gasto = validos.assign(p=validos["order_id"].map(pago_pedido).fillna(0)).groupby("customer_unique_id")["p"].sum()
    primero = validos.sort_values(["order_purchase_timestamp", "order_id"]).drop_duplicates("customer_unique_id")
    calif = primero.set_index("customer_unique_id")["order_id"].map(resenas.groupby("order_id")["review_score"].mean())
    rc["gasto_total"] = rc["customer_unique_id"].map(gasto)
    rc["calif_primer_pedido"] = rc["customer_unique_id"].map(calif)
    esperado = {"comparacion_recurrentes_vs_no": rc.groupby("es_recurrente", as_index=False).agg(
        clientes=("customer_unique_id", "size"), gasto_promedio=("gasto_total", "mean"),
        calificacion_primer_pedido_promedio=("calif_primer_pedido", "mean")).round(2)}

    items = order_items.merge(validos[["order_id", "customer_unique_id", "customer_state"]], on="order_id")
    items = items.merge(products[["product_id", "product_category_name"]], on="product_id")
    items = items.merge(traduccion, on="product_category_name", how="left")
    items["categoria"] = items["product_category_name_english"].fillna("sin_categoria")
    items = items.merge(rc[["customer_unique_id", "es_recurrente"]], on="customer_unique_id")
    rec = items[items["es_recurrente"] == 1]
    t = rec.groupby("categoria", as_index=False).agg(clientes_recurrentes=("customer_unique_id", "nunique"),
                                                     ingresos=("price", "sum"))
    esperado["top_10_categorias_recurrentes"] = t.sort_values("ingresos", ascending=False).head(10).round(2)
    e = rec.groupby("customer_state", as_index=False).agg(clientes_recurrentes=("customer_unique_id", "nunique"))
    esperado["top_10_estados_recurrentes"] = e.sort_values(["clientes_recurrentes", "customer_state"],
                                                           ascending=[False, True]).head(10)
    cc = items.drop_duplicates(["categoria", "customer_unique_id"])
    r = cc.groupby("categoria", as_index=False).agg(clientes=("customer_unique_id", "size"),
                                                    clientes_recurrentes=("es_recurrente", "sum"))
    r = r[r["clientes"] >= min_clientes_categoria].copy()
    r["tasa_recompra_pct"] = (100.0 * r["clientes_recurrentes"] / r["clientes"]).round(2)
    esperado["tasa_recompra_por_categoria"] = r

    obtenido = q01(min_clientes_categoria)["tablas"]
    lineas = []
    for nombre, df_p in esperado.items():
        df_s = obtenido[nombre]
        clave = list(df_s.columns)
        ordenar = lambda d: d[clave].sort_values(clave[::-1] if nombre != "tasa_recompra_por_categoria" else clave).reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(ordenar(df_p), ordenar(df_s), check_dtype=False, atol=0.005, rtol=0)
            lineas.append(f"[OK] q01 {nombre}: {len(df_s)} filas iguales a pandas")
        except AssertionError as err:
            lineas.append(f"[DIFF] q01 {nombre}: {str(err).splitlines()[0]}")
    return lineas


def main() -> None:
    pandas_vals = recalcular_con_pandas()
    sql_vals = _valores_sql()

    print("=== Verificación pandas (CSV) vs SQL (olist.db) ===")
    print(_comparar("Clientes únicos con pedido válido", pandas_vals["clientes_unicos"], sql_vals["clientes_unicos"], tolerancia=0))
    print(_comparar("% clientes recurrentes", pandas_vals["pct_recurrentes"], sql_vals["pct_recurrentes"]))
    print(_comparar("Ingresos categoría top (R$)", pandas_vals["ingresos_categoria_top"], sql_vals["ingresos_categoria_top"]))
    print(_comparar("% ingresos top 5 categorías", pandas_vals["pct_ingresos_top5_categorias"], sql_vals["pct_ingresos_top5_categorias"]))
    print(_comparar("% pedidos tardíos (global)", pandas_vals["pct_pedidos_tardios"], sql_vals["pct_pedidos_tardios"]))

    print("\n=== q01 completo: pandas (CSV) vs dashboard (olist.db) ===")
    for linea in verificar_q01_tablas():
        print(linea)

    print("\n=== Verificación pandas (CSV) vs oráculo (eval/ground_truth_olist.json) ===")
    for linea in verificar_oraculo():
        print(linea)


if __name__ == "__main__":
    main()
