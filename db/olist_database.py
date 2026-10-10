"""
Configuracion de conexion a la base de datos Olist (e-commerce).

Por defecto usa SQLite en db/olist.db, pero respeta la variable de entorno
OLIST_DATABASE_URL para apuntar a otro motor (ej. PostgreSQL) sin cambiar una
sola linea de codigo en el resto del proyecto (modelos, loader, modulo LLM).

Ejemplos de OLIST_DATABASE_URL:
  sqlite:///./db/olist.db                          (default)
  postgresql+psycopg2://usuario:pass@localhost/olist
"""
import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR / "olist.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

DATABASE_URL = os.environ.get("OLIST_DATABASE_URL", DEFAULT_DATABASE_URL)

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


def verificar_bd_existe(database_url: str = DATABASE_URL) -> None:
    """Con SQLite, `engine.connect()` crea un archivo vacío si la ruta no
    existe, y los errores posteriores ("no such table") confunden. Llamar a
    esta función antes de conectar falla con un mensaje claro. No aplica a
    otros motores ni a `:memory:`."""
    if not database_url.startswith("sqlite:///"):
        return
    ruta = database_url.replace("sqlite:///", "", 1)
    if ruta in ("", ":memory:"):
        return
    if not Path(ruta).is_file():
        raise FileNotFoundError(
            f"No existe la base de datos {Path(ruta).resolve()}. Créala con: "
            "python seeder/load_olist_csv.py"
        )


def get_session():
    """Devuelve una nueva sesion de SQLAlchemy. El caller es responsable de cerrarla."""
    return SessionLocal()


def get_readonly_connection(database_url: str = DATABASE_URL, timeout: int = 10) -> sqlite3.Connection:
    """Abre una conexion SQLite estrictamente de SOLO LECTURA (`mode=ro`), para
    que el pipeline LLM (llm/text_to_sql.py) nunca pueda escribir en olist.db
    aunque el SQL generado se le escapara al validador de llm/sql_guard.py."""
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "get_readonly_connection() solo soporta SQLite. Para PostgreSQL, usa "
            "una conexion con 'SET TRANSACTION READ ONLY' en su lugar."
        )
    db_path = database_url.replace("sqlite:///", "", 1)
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=timeout)
