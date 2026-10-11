"""
Configuracion de conexion a la base de datos.

Por defecto usa SQLite en legacy/gimnasio/db/gimnasio.db, pero respeta la variable de entorno
DATABASE_URL para apuntar a PostgreSQL sin cambiar una sola linea de codigo
en el resto del proyecto (modelos, seeder, modulo LLM), ya que todo el acceso
a datos pasa por SQLAlchemy.

Ejemplos de DATABASE_URL:
  sqlite:///./legacy/gimnasio/db/gimnasio.db                      (default)
  postgresql+psycopg2://usuario:pass@localhost/gimnasio
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR / "gimnasio.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session():
    """Devuelve una nueva sesion de SQLAlchemy. El caller es responsable de cerrarla."""
    return SessionLocal()
