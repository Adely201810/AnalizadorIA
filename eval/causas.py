"""
Atribuye cada fallo de DESARROLLO a las causas medidas en la etapa 1 (Paso 3):
  (a) descompuesta: el clasificador partió en sub-consultas una pregunta de una sola consulta;
  (b) sin_filtro_valido: la referencia exige pedido válido y el SQL final del modelo
      no filtra order_status (ni usa una vista que ya excluye canceled/unavailable);
  (c) denominador: pregunta de porcentaje, con el filtro de pedido válido
      presente cuando hace falta, que corrió y dio un valor incorrecto
      (heurística: el denominador u otra parte del cálculo es distinta);
  otro: el resto (errores de ejecución, rankings, etc.).
Un fallo recibe UNA causa, en el orden a > b > c > otro.

Uso: python -m eval.causas eval/baselines/etapa2/base_r1.json [más archivos]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

GT = {q["id"]: q for q in json.loads((Path(__file__).resolve().parent / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]}
VISTAS_YA_FILTRADAS = ("vw_ingresos_por_categoria", "vw_ingresos_por_vendedor", "vw_clientes_recurrentes", "vw_pedidos_validos")


def causa(r: dict) -> str:
    q = GT[r["id"]]
    sql = (r.get("sql_generado") or "").lower()
    if r["origen"] is None and not r.get("error_pipeline"):
        return "a_descompuesta"
    exige_valido = "order_status not in" in q["sql_referencia"].lower()
    filtra = ("canceled" in sql or "unavailable" in sql or "order_status" in sql
              or any(v in sql for v in VISTAS_YA_FILTRADAS))
    if exige_valido and sql and not filtra:
        return "b_sin_filtro_valido"
    if "porcentaje" in q["tipos_columnas"] and r.get("total_filas_modelo") and r["clasificacion"] == "semantico":
        return "c_denominador"
    return "otro"


def main(rutas: list[str]) -> None:
    total = Counter()
    for ruta in rutas:
        d = json.loads(Path(ruta).read_text(encoding="utf-8"))
        fallos = [r for r in d["resultados"] if not r["correcto"]]
        c = Counter(causa(r) for r in fallos)
        total.update(c)
        print(f"{Path(ruta).name}: {len(fallos)} fallos -> {dict(sorted(c.items()))}")
        for r in fallos:
            print(f"   {r['id']:42s} {causa(r):20s} {r['clasificacion']:10s} {(r.get('sql_generado') or '')[:110]!r}")
    print(f"TOTAL ({len(rutas)} corridas): {dict(sorted(total.items()))}")


if __name__ == "__main__":
    main(sys.argv[1:])
