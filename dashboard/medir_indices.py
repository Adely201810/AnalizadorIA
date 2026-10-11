"""
Mide si índices sobre llaves foráneas aceleran las consultas del dashboard
(Fase 11, problema P3: q01 tardaba ~42 s). Trabaja SIEMPRE sobre una COPIA de la
base: nunca crea índices en db/olist.db.

Uso:
    python -m dashboard.medir_indices --copia <ruta_copia.db> [--repeticiones 2]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGINAL = RAIZ / "db" / "olist.db"

INDICES = [
    "CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_items_product_id ON order_items(product_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_items_seller_id ON order_items(seller_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_reviews_order_id ON order_reviews(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_customers_unique_id ON customers(customer_unique_id)",
]

_CRONO = """
import sys, time
from dashboard import queries as q
for n in sys.argv[1:]:
    t = time.perf_counter(); getattr(q, f"q{int(n):02d}")(); print(f"q{int(n):02d} {time.perf_counter() - t:.2f}", flush=True)
"""


def cronometrar(db: Path, consultas: list[str]) -> dict[str, float]:
    """Cada medición en un proceso nuevo apuntando a `db` (sin caché de Python)."""
    env = {**__import__("os").environ, "OLIST_DATABASE_URL": f"sqlite:///{db.as_posix()}", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", _CRONO, *consultas], cwd=RAIZ, env=env,
                         capture_output=True, text=True, check=True).stdout
    return {l.split()[0]: float(l.split()[1]) for l in out.splitlines() if l.startswith("q")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copia", required=True)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--consultas", nargs="+", default=[str(i) for i in range(1, 11)])
    args = ap.parse_args()
    copia = Path(args.copia)
    if copia.resolve() == ORIGINAL.resolve():
        sys.exit("La copia no puede ser la base original.")
    shutil.copyfile(ORIGINAL, copia)
    print(f"copia: {copia} ({copia.stat().st_size:,} bytes)")

    for r in range(1, args.repeticiones + 1):
        print(f"SIN índices (rep {r}): {cronometrar(copia, args.consultas)}", flush=True)
    conn = sqlite3.connect(copia)
    t = time.perf_counter()
    for sql in INDICES:
        conn.execute(sql)
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    print(f"índices creados en la COPIA en {time.perf_counter() - t:.1f} s: {[s.split()[5] for s in INDICES]}")
    for r in range(1, args.repeticiones + 1):
        print(f"CON índices (rep {r}): {cronometrar(copia, args.consultas)}", flush=True)


if __name__ == "__main__":
    main()
