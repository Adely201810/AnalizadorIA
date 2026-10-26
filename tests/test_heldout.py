"""
Conjuntos held-out y principio de no-derivación del contexto.

Etapa 2, Paso 2: el conjunto de PRUEBA no puede filtrarse a nada que el modelo vea.
Etapa 3, Paso 2: el PRUEBA de la v3 ya se vio y pasó a DESARROLLO (oráculo v4).
El held-out ahora es PRUEBA_2 (20 preguntas nuevas). Además, por el principio de la
etapa 3, NADA del contexto puede derivarse de NINGUNA pregunta del oráculo (ni de
DESARROLLO ni de PRUEBA_2).

Comprueba que:
  - el split versionado (eval/split_oraculo.json) coincide con el oráculo: DESARROLLO 30
    (con las 10 necesidades) y PRUEBA_2 20, y cada pregunta de PRUEBA_2 lleva su tipo;
  - ningún ejemplo few-shot (ni del clasificador) se parece a una pregunta o a un SQL de
    PRUEBA_2 (mismos umbrales que tests/test_fewshot_disjunto.py, que además cubre las 50);
  - el prompt completo del generador de SQL no contiene fragmentos de 4 palabras de
    NINGUNA de las 50 preguntas ni, para PRUEBA_2, ninguna forma escrita de sus resultados;
  - la bitácora persistente (si existe) no contiene preguntas ni valores de PRUEBA_2;
  - la evaluación no usa la bitácora y, por defecto, solo evalúa DESARROLLO; eval.ab
    rechaza PRUEBA_2;
  - la app de chat no ofrece preguntas de PRUEBA_2 como ejemplos.

Uso: python -m unittest tests.test_heldout -v
"""
import json
import re
import unittest
from pathlib import Path

from eval.pistas import fugas, valores_de_referencia
from eval.similitud import _normalizar, jaccard, tokens_sql, tokens_texto
from llm.bitacora import BitacoraEsquema
from llm.schema_context import EJEMPLOS_DENOMINADOR, EJEMPLOS_FEW_SHOT, EJEMPLOS_MULTIPLICIDAD, get_schema_context
from llm.text_to_sql import CLASIFICADOR_SYSTEM_PROMPT, SQL_SYSTEM_PROMPT_TEMPLATE

# Incluye los few-shot de las mejoras con interruptor (Etapa 2, Paso 3) aunque estén apagados.
# Etapa 3: también el banco del few-shot dinámico (E5), aunque esté apagado.
from llm.contexto_e3 import banco as _banco_e5
TODOS_LOS_EJEMPLOS = list(dict.fromkeys(EJEMPLOS_FEW_SHOT + EJEMPLOS_DENOMINADOR + EJEMPLOS_MULTIPLICIDAD + _banco_e5()))

RAIZ = Path(__file__).resolve().parent.parent
ORACULO = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
SPLIT = json.loads((RAIZ / "eval" / "split_oraculo.json").read_text(encoding="utf-8"))
PRUEBA_2 = [q for q in ORACULO if q["conjunto"] == "prueba_2"]
TIPOS_PRUEBA_2 = {"simple", "porcentaje", "pedido_valido", "ranking", "varios_pasos"}
# 4 palabras: con 5 o 6 no se detectaba la nota "peso del flete sobre el precio", que
# calcaba la pregunta n05 (ver docs/CONTEXTO_ACTUAL.md, laguna 9, y D-27).
N_TEJA = 4


def _shingles(texto: str, n: int = N_TEJA) -> set[str]:
    palabras = re.findall(r"[a-z0-9_]+", _normalizar(texto))
    return {" ".join(palabras[i:i + n]) for i in range(len(palabras) - n + 1)}


def _prompt_completo() -> str:
    # Etapa 3: incluye todo lo que algún interruptor podría inyectar (glosario, banco de ejemplos,
    # descripciones de columnas, vistas de negocio, regla del plan), esté encendido o no.
    from llm.contexto_e3 import todo_el_texto_opcional
    return (SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context()) + "\n" + CLASIFICADOR_SYSTEM_PROMPT
            + "\n" + todo_el_texto_opcional())


class TestSplit(unittest.TestCase):
    def test_split_coincide_con_el_oraculo(self):
        self.assertEqual(len(ORACULO), 50)
        self.assertEqual(sorted(SPLIT["prueba_2"]), sorted(q["id"] for q in PRUEBA_2))
        self.assertEqual(sorted(SPLIT["desarrollo"]), sorted(q["id"] for q in ORACULO if q["conjunto"] == "desarrollo"))
        self.assertEqual((len(SPLIT["desarrollo"]), len(SPLIT["prueba_2"])), (30, 20))
        self.assertEqual({q["conjunto"] for q in ORACULO}, {"desarrollo", "prueba_2"})

    def test_las_10_necesidades_estan_en_desarrollo(self):
        necesidades = [q for q in ORACULO if q.get("pestana_dashboard")]
        self.assertEqual(len(necesidades), 10)
        self.assertTrue(all(q["conjunto"] == "desarrollo" for q in necesidades))

    def test_prueba_2_etiquetada_por_tipo(self):
        self.assertTrue(all(q.get("tipo") in TIPOS_PRUEBA_2 for q in PRUEBA_2))
        self.assertEqual({q["tipo"] for q in PRUEBA_2}, TIPOS_PRUEBA_2)


class TestPrueba2NoSeFiltra(unittest.TestCase):
    def test_fewshot_lejos_de_prueba_2(self):
        for pregunta, sql in TODOS_LOS_EJEMPLOS:
            for q in PRUEBA_2:
                self.assertLess(jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"])), 0.25, (pregunta, q["id"]))
                self.assertLess(jaccard(tokens_sql(sql), tokens_sql(q["sql_referencia"])), 0.5, (pregunta, q["id"]))

    def test_clasificador_lejos_de_prueba_2(self):
        for pregunta in re.findall(r"Pregunta: (.+)", CLASIFICADOR_SYSTEM_PROMPT):
            for q in PRUEBA_2:
                self.assertLess(jaccard(tokens_texto(pregunta), tokens_texto(q["pregunta"])), 0.25, (pregunta, q["id"]))

    def test_prompt_sin_resultados_de_prueba_2(self):
        prompt = _prompt_completo()
        for q in PRUEBA_2:
            tipos = [t for f in q["resultado_esperado"] for t in q["tipos_columnas"] if t is not None]
            for v, tipo in zip(valores_de_referencia(q["resultado_esperado"], q["tipos_columnas"]), tipos):
                encontradas = fugas(prompt, [v])
                if tipo == "conteo":
                    # Un conteo solo se filtra con su forma entera exacta (1529, 1,529): las formas
                    # x100 / /100 de eval.pistas son para porcentajes y daban "15" (choca con "15+")
                    # o "100.0" (choca con el "100.0 *" de los ejemplos SQL).
                    encontradas = [f for f in encontradas if re.sub(r",", "", f) == str(int(v))]
                elif isinstance(v, float) and not v.is_integer():
                    # Para un valor no entero, su redondeo a entero choca con números naturales
                    # del prompt (p. ej. el rango "15+"): solo cuentan las formas con decimales.
                    encontradas = [f for f in encontradas if not f.lstrip("-").isdigit()]
                self.assertEqual(encontradas, [], f"{q['id']}: su resultado {v!r} aparece en el prompt")

    def test_bitacora_sin_contenido_de_prueba_2(self):
        b = BitacoraEsquema()  # la bitácora real del chat (runtime/), si existe
        # Solo el CONTENIDO que vuelve al prompt (D-48): las marcas de tiempo y los contadores daban falsos
        # positivos (los segundos "19" de "13:57:19" coinciden con la forma /100 de 1891, de p2_03).
        texto = json.dumps([{k: e.get(k) for k in ("clave", "mensaje", "ejemplo_pregunta")} for e in b.entradas()],
                           ensure_ascii=False)
        for q in PRUEBA_2:
            self.assertNotIn(_normalizar(q["pregunta"])[:60], _normalizar(texto), q["id"])
            self.assertEqual(fugas(texto, valores_de_referencia(q["resultado_esperado"], q["tipos_columnas"])), [], q["id"])

    def test_evaluacion_no_usa_bitacora_y_por_defecto_es_desarrollo(self):
        fuente = (RAIZ / "eval" / "run_eval.py").read_text(encoding="utf-8")
        self.assertNotIn("BitacoraEsquema", fuente)
        self.assertNotIn("bitacora=", fuente)
        self.assertRegex(fuente, r'"--conjunto".*default="desarrollo"')
        self.assertIn('"prueba_2"', (RAIZ / "eval" / "ab.py").read_text(encoding="utf-8"))

    def test_app_no_ofrece_preguntas_de_prueba_2(self):
        fuente = (RAIZ / "app.py").read_text(encoding="utf-8")
        self.assertIn('if item.get("pestana_dashboard")', fuente)


class TestContextoNoDerivaDelOraculo(unittest.TestCase):
    """Principio de la etapa 3: ni DESARROLLO ni PRUEBA_2 aportan texto al contexto."""

    def test_prompt_sin_fragmentos_de_ninguna_pregunta(self):
        tejas = _shingles(_prompt_completo())
        for q in ORACULO:
            comunes = _shingles(q["pregunta"]) & tejas
            self.assertFalse(comunes, f"{q['id']} ({q['conjunto']}): fragmentos de la pregunta en el prompt: {comunes}")


if __name__ == "__main__":
    unittest.main()
