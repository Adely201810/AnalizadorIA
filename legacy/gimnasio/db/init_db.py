"""
Crea (o recrea) el esquema completo de la base de datos: tablas ORM + vistas analíticas.

Uso:
    python legacy/gimnasio/db/init_db.py               # crea las tablas si no existen
    python legacy/gimnasio/db/init_db.py --reset       # elimina todo y vuelve a crear (destructivo)
    python legacy/gimnasio/db/init_db.py --export-ddl  # además exporta el DDL resultante a legacy/gimnasio/db/schema.sql
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raíz del repositorio

from sqlalchemy.schema import CreateTable

from legacy.gimnasio.db.database import DATABASE_URL, engine
from legacy.gimnasio.db.models import Base


def reset_schema():
    Base.metadata.drop_all(bind=engine)
    print("Tablas existentes eliminadas.")


def create_schema():
    Base.metadata.create_all(bind=engine)
    print(f"Tablas creadas en: {DATABASE_URL}")


def create_views():
    raw_sql = (Path(__file__).resolve().parent / "views.sql").read_text(encoding="utf-8")
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
    print("Vistas analíticas creadas: vw_ingresos_netos_mensuales, vw_retencion_churn_trimestral, vw_ltv_cliente")


def export_ddl():
    lines = ["-- DDL exportado automáticamente desde db/models.py (SQLAlchemy) --\n"]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(engine)).strip()
        lines.append(ddl + ";\n")
    out_path = Path(__file__).resolve().parent / "schema.sql"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"DDL exportado a: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa el esquema de la base de datos del gimnasio.")
    parser.add_argument("--reset", action="store_true", help="Elimina todas las tablas antes de crearlas (destructivo).")
    parser.add_argument("--export-ddl", action="store_true", help="Exporta el DDL resultante a legacy/gimnasio/db/schema.sql")
    args = parser.parse_args()

    if args.reset:
        reset_schema()

    create_schema()
    create_views()

    if args.export_ddl:
        export_ddl()
