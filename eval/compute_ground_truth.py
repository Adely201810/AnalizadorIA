"""
Recalcula y muestra los valores de referencia (ground truth) de un archivo
eval/ground_truth*.json ejecutando directamente el SQL de referencia contra la
base de datos actual.

Útil para:
  - Verificar que el ground truth sigue siendo consistente con los datos.
  - Regenerar los valores si se recargó/reseembró la base de datos.

Uso:
    python eval/compute_ground_truth.py                          # olist (default)
    python eval/compute_ground_truth.py --dataset gimnasio
    python eval/compute_ground_truth.py --ground-truth eval/otro.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

DEFAULT_GROUND_TRUTH = {
    "olist": Path(__file__).resolve().parent / "ground_truth_olist.json",
    "gimnasio": Path(__file__).resolve().parent / "ground_truth.json",
}


def _engine_for(dataset: str):
    if dataset == "gimnasio":
        from db.database import engine
    else:
        from db.olist_database import engine
    return engine


def main():
    parser = argparse.ArgumentParser(description="Recalcula el ground truth contra la base de datos actual.")
    parser.add_argument("--dataset", choices=["olist", "gimnasio"], default="olist")
    parser.add_argument("--ground-truth", type=Path, default=None, help="Override de la ruta del JSON de ground truth")
    args = parser.parse_args()

    ground_truth_path = args.ground_truth or DEFAULT_GROUND_TRUTH[args.dataset]
    engine = _engine_for(args.dataset)

    data = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    with engine.connect() as conn:
        for item in data["preguntas"]:
            rows = conn.execute(text(item["sql_referencia"])).fetchall()
            print(f"{item['id']:32s} -> {rows}")


if __name__ == "__main__":
    main()
