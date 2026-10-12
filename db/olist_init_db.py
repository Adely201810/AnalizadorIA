"""
Crea (o recrea) el esquema completo de la base de datos Olist: tablas ORM +
vistas analíticas.

Uso:
    python db/olist_init_db.py               # crea las tablas si no existen
    python db/olist_init_db.py --reset       # elimina todo y vuelve a crear (destructivo)
    python db/olist_init_db.py --export-ddl  # además exporta el DDL resultante a db/olist_schema.sql
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.schema import CreateTable

from db.olist_database import DATABASE_URL, engine
from db.olist_models import OlistBase


def reset_schema():
    OlistBase.metadata.drop_all(bind=engine)
    print("Tablas existentes eliminadas.")


def create_schema():
    OlistBase.metadata.create_all(bind=engine)
    print(f"Tablas creadas en: {DATABASE_URL}")


def create_views():
    raw_sql = (Path(__file__).resolve().parent / "olist_views.sql").read_text(encoding="utf-8")
    # Elimina líneas de comentario ("-- ...") antes de partir por ";", para no
    # perder statements cuyo primer renglón (tras el split) sea un comentario.
    sin_comentarios = "\n".join(
        line for line in raw_sql.splitlines() if not line.strip().startswith("--")
    )
    statements = [s.strip() for s in sin_comentarios.split(";") if s.strip()]
    with engine.begin() as conn:
        from sqlalchemy import text

        for stmt in statements:
            conn.execute(text(stmt))
    print(
        "Vistas analíticas creadas: vw_ventas_pedido, vw_clientes_recurrentes, "
        "vw_entregas_retrasos, vw_ingresos_por_categoria, vw_ingresos_por_vendedor, "
        "vw_retraso_por_rango, vw_pedidos_validos, vw_pedidos_entregados, vw_totales_pedido, vw_articulos_vendidos"
    )


def export_ddl():
    lines = ["-- DDL exportado automáticamente desde db/olist_models.py (SQLAlchemy) --\n"]
    for table in OlistBase.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(engine)).strip()
        lines.append(ddl + ";\n")
    out_path = Path(__file__).resolve().parent / "olist_schema.sql"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"DDL exportado a: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa el esquema de la base de datos Olist.")
    parser.add_argument("--reset", action="store_true", help="Elimina todas las tablas antes de crearlas (destructivo).")
    parser.add_argument("--export-ddl", action="store_true", help="Exporta el DDL resultante a db/olist_schema.sql")
    args = parser.parse_args()

    if args.reset:
        reset_schema()

    create_schema()
    create_views()

    if args.export_ddl:
        export_ddl()
