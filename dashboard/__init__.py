"""
Dashboard de verificación (sin IA) para AnalizadorIA.

Responde con SQL directo sobre las TABLAS BASE de db/olist.db (nunca sobre
las vistas vw_* que usa el chatbot) las 10 necesidades del dueño, para poder
comparar sus respuestas contra las del chatbot y confirmar que la base de
datos sí contiene la información. No importa ni modifica app.py, llm/ ni
eval/.
"""
from .queries import q01, q02, q03, q04, q05, q06, q07, q08, q09, q10

__all__ = ["q01", "q02", "q03", "q04", "q05", "q06", "q07", "q08", "q09", "q10"]
