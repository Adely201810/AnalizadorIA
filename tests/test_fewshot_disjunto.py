"""
Fase 1: los ejemplos del prompt (entrenamiento) y las preguntas del oráculo
(evaluación) deben ser conjuntos disjuntos, y el contexto de esquema debe
declarar el tipo de todas las columnas.

Umbrales de Jaccard (eval/similitud.py), calibrados con la matriz previa a la
separación (docs/FASE_01.md): los ejemplos que duplicaban preguntas del
oráculo tenían texto >= 0.294 o SQL >= 0.667; los demás, texto <= 0.167 y
SQL <= 0.389.

Uso: python -m unittest tests.test_fewshot_disjunto -v
"""
import re
import sqlite3
import unittest
from pathlib import Path

from eval.similitud import jaccard, preguntas_oraculo, tokens_sql, tokens_texto
from llm.schema_context import EJEMPLOS_DENOMINADOR, EJEMPLOS_FEW_SHOT, EJEMPLOS_MULTIPLICIDAD, get_schema_context

# Incluye los few-shot de las mejoras con interruptor (Etapa 2, Paso 3) aunque estén apagados.
# Etapa 3: también el banco del few-shot dinámico (E5), aunque esté apagado.
from llm.contexto_e3 import banco as _banco_e5
TODOS_LOS_EJEMPLOS = list(dict.fromkeys(EJEMPLOS_FEW_SHOT + EJEMPLOS_DENOMINADOR + EJEMPLOS_MULTIPLICIDAD + _banco_e5()))
from llm.text_to_sql import CLASIFICADOR_SYSTEM_PROMPT

UMBRAL_TEXTO = 0.25
UMBRAL_SQL = 0.5
DB_PATH = Path(__file__).resolve().parent.parent / "db" / "olist.db"


class TestFewShotDisjunto(unittest.TestCase):
    def test_preguntas_fewshot_lejos_del_oraculo(self):
        for pregunta, _ in TODOS_LOS_EJEMPLOS:
            for q in preguntas_oraculo():
                j = jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"]))
                self.assertLess(j, UMBRAL_TEXTO, f"{pregunta!r} ~ {q['id']} (texto {j:.3f})")

    def test_sql_fewshot_lejos_del_oraculo(self):
        for pregunta, sql in TODOS_LOS_EJEMPLOS:
            for q in preguntas_oraculo():
                j = jaccard(tokens_sql(sql), tokens_sql(q["sql_referencia"]))
                self.assertLess(j, UMBRAL_SQL, f"{pregunta!r} ~ {q['id']} (SQL {j:.3f})")

    def test_ejemplos_del_clasificador_lejos_del_oraculo(self):
        ejemplos = re.findall(r"Pregunta: (.+)", CLASIFICADOR_SYSTEM_PROMPT)
        self.assertGreater(len(ejemplos), 0)
        for pregunta in ejemplos:
            for q in preguntas_oraculo():
                j = jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"]))
                self.assertLess(j, UMBRAL_TEXTO, f"clasificador {pregunta!r} ~ {q['id']} (texto {j:.3f})")

    def test_sql_fewshot_ejecuta_y_devuelve_filas(self):
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            for pregunta, sql in TODOS_LOS_EJEMPLOS:
                filas = conn.execute(sql).fetchall()
                self.assertGreater(len(filas), 0, pregunta)
        finally:
            conn.close()


class TestTiposEnEsquema(unittest.TestCase):
    TIPOS = ("TEXT", "INTEGER", "NUMERIC", "REAL", "DATETIME")

    def _columnas(self):
        ctx = get_schema_context()
        bloque = ctx[: ctx.index("Columnas de unión")]
        for linea in bloque.splitlines():
            # No voraz: la descripción de una vista puede traer paréntesis, ej. "(días)".
            m = re.match(r"^-? ?(\w+)\((.*?)\)(?: --|$)", linea.strip())
            if m:
                for col in m.group(2).split(", "):
                    yield m.group(1), col

    def test_toda_columna_tiene_tipo(self):
        columnas = list(self._columnas())
        self.assertGreater(len(columnas), 60)
        for tabla, col in columnas:
            self.assertTrue(any(t in col.split() for t in self.TIPOS), f"{tabla}: {col!r} sin tipo")

    def test_sin_tipo_string(self):
        self.assertNotIn("STRING", get_schema_context())


if __name__ == "__main__":
    unittest.main()
