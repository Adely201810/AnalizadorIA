"""
Etapa 2, Paso 2: el conjunto de PRUEBA (held-out) no puede filtrarse a nada
que el modelo vea ni a nada que se ajuste con él.

Comprueba que:
  - el split versionado (eval/split_oraculo.json) coincide con el oráculo, y las
    10 necesidades del dashboard están en DESARROLLO;
  - ningún ejemplo few-shot (ni del clasificador) se parece a una pregunta o a un
    SQL de PRUEBA (mismos umbrales que tests/test_fewshot_disjunto.py);
  - el prompt completo del generador de SQL (esquema, reglas, ejemplos) no
    contiene fragmentos de 6 palabras de las preguntas de PRUEBA ni ninguna
    forma escrita de sus resultados esperados;
  - la bitácora persistente (si existe) no contiene preguntas ni valores de PRUEBA;
  - la evaluación no usa la bitácora y, por defecto, solo evalúa DESARROLLO;
  - la app de chat no ofrece preguntas de PRUEBA como ejemplos.

Uso: python -m unittest tests.test_heldout -v
"""
import json
import re
import unittest
from pathlib import Path

from eval.pistas import formas_de_valor, fugas, valores_de_referencia
from eval.similitud import _normalizar, jaccard, tokens_sql, tokens_texto
from llm.bitacora import BitacoraEsquema
from llm.schema_context import EJEMPLOS_FEW_SHOT, get_schema_context
from llm.text_to_sql import CLASIFICADOR_SYSTEM_PROMPT, SQL_SYSTEM_PROMPT_TEMPLATE

RAIZ = Path(__file__).resolve().parent.parent
ORACULO = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
SPLIT = json.loads((RAIZ / "eval" / "split_oraculo.json").read_text(encoding="utf-8"))
PRUEBA = [q for q in ORACULO if q["conjunto"] == "prueba"]


def _shingles(texto: str, n: int = 6) -> set[str]:
    palabras = re.findall(r"[a-z0-9_]+", _normalizar(texto))
    return {" ".join(palabras[i:i + n]) for i in range(len(palabras) - n + 1)}


class TestSplit(unittest.TestCase):
    def test_split_coincide_con_el_oraculo(self):
        self.assertEqual(len(ORACULO), 30)
        self.assertEqual(sorted(SPLIT["prueba"]), sorted(q["id"] for q in PRUEBA))
        self.assertEqual(sorted(SPLIT["desarrollo"]), sorted(q["id"] for q in ORACULO if q["conjunto"] == "desarrollo"))
        self.assertEqual((len(SPLIT["desarrollo"]), len(SPLIT["prueba"])), (20, 10))

    def test_las_10_necesidades_estan_en_desarrollo(self):
        necesidades = [q for q in ORACULO if q.get("pestana_dashboard")]
        self.assertEqual(len(necesidades), 10)
        self.assertTrue(all(q["conjunto"] == "desarrollo" for q in necesidades))


class TestPruebaNoSeFiltra(unittest.TestCase):
    def test_fewshot_lejos_de_prueba(self):
        for pregunta, sql in EJEMPLOS_FEW_SHOT:
            for q in PRUEBA:
                self.assertLess(jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"])), 0.25, (pregunta, q["id"]))
                self.assertLess(jaccard(tokens_sql(sql), tokens_sql(q["sql_referencia"])), 0.5, (pregunta, q["id"]))

    def test_clasificador_lejos_de_prueba(self):
        for pregunta in re.findall(r"Pregunta: (.+)", CLASIFICADOR_SYSTEM_PROMPT):
            for q in PRUEBA:
                self.assertLess(jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"])), 0.25, (pregunta, q["id"]))

    def test_prompt_sin_fragmentos_ni_resultados_de_prueba(self):
        prompt = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context()) + "\n" + CLASIFICADOR_SYSTEM_PROMPT
        tejas_prompt = _shingles(prompt)
        for q in PRUEBA:
            comunes = _shingles(q["pregunta"]) & tejas_prompt
            self.assertFalse(comunes, f"{q['id']}: fragmentos de la pregunta en el prompt: {comunes}")
            for v in valores_de_referencia(q["resultado_esperado"], q["tipos_columnas"]):
                encontradas = fugas(prompt, [v])
                if isinstance(v, float) and not v.is_integer():
                    # Para un valor no entero, su redondeo a entero (p. ej. 15.31 -> "15") choca con
                    # números naturales del prompt (el rango "15+" de vw_retraso_por_rango): solo
                    # cuentan las formas con decimales.
                    encontradas = [f for f in encontradas if not f.lstrip("-").isdigit()]
                self.assertEqual(encontradas, [], f"{q['id']}: su resultado {v!r} aparece en el prompt")

    def test_bitacora_sin_contenido_de_prueba(self):
        b = BitacoraEsquema()  # la bitácora real del chat (runtime/), si existe
        texto = json.dumps(b.entradas(), ensure_ascii=False)
        for q in PRUEBA:
            self.assertNotIn(_normalizar(q["pregunta"])[:60], _normalizar(texto), q["id"])
            self.assertEqual(fugas(texto, valores_de_referencia(q["resultado_esperado"], q["tipos_columnas"])), [], q["id"])

    def test_evaluacion_no_usa_bitacora_y_por_defecto_es_desarrollo(self):
        fuente = (RAIZ / "eval" / "run_eval.py").read_text(encoding="utf-8")
        self.assertNotIn("BitacoraEsquema", fuente)
        self.assertNotIn("bitacora=", fuente)
        self.assertRegex(fuente, r'"--conjunto".*default="desarrollo"')

    def test_app_no_ofrece_preguntas_de_prueba(self):
        fuente = (RAIZ / "app.py").read_text(encoding="utf-8")
        self.assertIn('if item.get("pestana_dashboard")', fuente)


if __name__ == "__main__":
    unittest.main()
