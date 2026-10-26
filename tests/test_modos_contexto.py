"""
Modos de contexto (D-42 a D-45): few-shot fijo, RAG, presupuesto de tokens y harness.

- Con el modo por defecto ("base") el prompt del generador es el de siempre.
- Few-shot: N fijos, uno por familia, y el bloque entra en el prompt de usuario.
- RAG: índice persistido y vigente; para cada necesidad REAL el top-1 es de la familia correcta
  (embeddings; se salta si Ollama no responde) y la familia aparece en el top-3 (tfidf, sin Ollama).
  Una pregunta ajena a la base no recibe ejemplos.
- Presupuesto: el bloque se recorta hasta caber en num_ctx.
- Harness: hasta 5 intentos, verificador sin oráculo y registro por intento.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import requests

from llm import fewshot, modo_contexto, rag
from llm import text_to_sql as t
from llm.banco_ejemplos import cargar_banco

RAIZ = Path(__file__).resolve().parent.parent


def _necesidades_reales() -> list[tuple[str, str, str]]:
    """(id, dígito de familia, pregunta) de las necesidades 2, 4, 5, 6 y 8: casos del juez y DESARROLLO."""
    casos = json.loads((RAIZ / "eval" / "casos_juez.json").read_text(encoding="utf-8"))["casos"]
    gt = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
    return ([(c["id"], c["necesidad"][0], c["pregunta"]) for c in casos if c["id"].startswith("n")]
            + [(q["id"], q["id"][2], q["pregunta"]) for q in gt if q["id"][:3] in ("n02", "n04", "n05", "n06", "n08")])


def _ollama_embeddings_disponible() -> bool:
    try:
        rag._embed(["prueba"])
        return True
    except (requests.RequestException, KeyError):
        return False


class _Guion:
    """Cliente falso: guarda los prompts del generador de SQL y responde con un SQL válido."""
    model, host, temperature, num_ctx = "falso", "-", 0.0, 8192

    def __init__(self, sql="SELECT COUNT(*) AS n FROM orders", juez='{"tiene_sentido": true, "motivo": "ok"}'):
        self.prompts_sql, self.sql, self.juez = [], sql, juez

    def generate(self, prompt, system=None, **kw):
        s = system or ""
        if s.startswith("Eres un generador de consultas SQL"):
            self.prompts_sql.append(prompt)
            return f"```sql\n{self.sql}\n```"
        if s.startswith("Eres un revisor experto"):
            return self.juez
        return "Hay 99,441 pedidos."


class TestFewShot(unittest.TestCase):
    def test_uno_por_familia_en_orden(self):
        fams = [e["familia"] for e in fewshot.ejemplos_fijos(5)]
        self.assertEqual(len(set(fams)), 5)
        self.assertEqual([e["id"] for e in fewshot.ejemplos_fijos(3)], [e["id"] for e in fewshot.ejemplos_fijos(5)][:3])
        self.assertEqual(len(fewshot.ejemplos_fijos(7)), 7)

    def test_bloque_con_y_sin_respuesta(self):
        ej = [{"entrada": e, "similitud": None} for e in fewshot.ejemplos_fijos(2)]
        sin = fewshot.texto_bloque(ej, recuperados=False, con_respuesta=False)
        con = fewshot.texto_bloque(ej, recuperados=False, con_respuesta=True)
        self.assertIn("SQL:", sin)
        self.assertNotIn("Respuesta:", sin)
        self.assertIn(ej[0]["entrada"]["respuesta_nl"], con)

    def test_presupuesto_recorta_hasta_caber(self):
        ej = [{"entrada": e, "similitud": None} for e in cargar_banco()]  # los 35: no caben
        recortado = fewshot.ajustar_a_presupuesto(ej)
        self.assertLess(len(recortado), len(ej))
        self.assertGreater(len(recortado), 3)
        sistema = t.SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=t.get_schema_context())
        self.assertTrue(fewshot.cabe(sistema, "", fewshot.texto_bloque(recortado, recuperados=False)))
        self.assertEqual(fewshot.ajustar_a_presupuesto(ej, num_ctx=2048), [])  # sin espacio: sin ejemplos


class TestModosEnElPrompt(unittest.TestCase):
    def _prompt(self, modo):
        c = _Guion()
        with mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1):
            r = t.answer_question("¿Cuántos pedidos hay en total?", client=c, usar_plantillas=False, modo=modo)
        return c.prompts_sql[0], r

    def test_base_no_cambia_el_prompt(self):
        prompt, r = self._prompt("base")
        self.assertEqual(prompt, "Pregunta: ¿Cuántos pedidos hay en total?")
        self.assertEqual(r.modo, "base")
        self.assertEqual(r.ejemplos_usados, [])

    def test_fewshot_inyecta_los_fijos(self):
        prompt, r = self._prompt("fewshot")
        self.assertIn(fewshot.ENCABEZADO_FIJO, prompt)
        self.assertEqual([e["id"] for e in r.ejemplos_usados], [e["id"] for e in fewshot.ejemplos_fijos()])

    def test_rag_inyecta_recuperados_con_similitud(self):
        with mock.patch.object(rag, "MOTOR_POR_DEFECTO", "tfidf"):
            c = _Guion()
            with mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1):
                r = t.answer_question("¿Qué porcentaje de los pedidos pagados con boleto llegó tarde a SP?",
                                      client=c, usar_plantillas=False, modo="rag")
        self.assertIn(fewshot.ENCABEZADO_RAG, c.prompts_sql[0])
        self.assertTrue(r.ejemplos_usados)
        self.assertTrue(all(e["similitud"] is not None for e in r.ejemplos_usados))

    def test_export_json_trae_la_trazabilidad(self):
        _, r = self._prompt("fewshot")
        d = t.exportar_resultado_json(r, r.pregunta, "falso", temperatura=0.3)
        for k in ("modo", "ejemplos_usados", "modelo", "temperatura", "intentos"):
            self.assertIn(k, d)
        self.assertEqual(d["modo"], "fewshot")

    def test_modo_desconocido(self):
        with self.assertRaises(ValueError):
            with modo_contexto.usar_modo("otro"):
                pass


class TestRAG(unittest.TestCase):
    def test_indice_persistido_y_vigente(self):
        for motor in ("tfidf",):
            ind = rag.indice(motor)
            self.assertEqual(ind["hash_banco"], rag.hash_banco())
            self.assertTrue((rag.DIR_INDICE / f"{motor}.json").exists())
        self.assertTrue((rag.DIR_INDICE / "umbrales.json").exists())

    def test_tfidf_familia_correcta_en_el_top3(self):
        fam = {e["id"]: e["familia"][0] for e in cargar_banco()}
        for i, f, p in _necesidades_reales():
            top3 = [fam[x] for x, _ in rag.puntuaciones(p, "tfidf")[:3]]
            self.assertIn(f, top3, i)

    def test_embeddings_top1_de_la_familia_correcta(self):
        if not _ollama_embeddings_disponible():
            self.skipTest("Ollama / nomic-embed-text no disponible")
        fam = {e["id"]: e["familia"][0] for e in cargar_banco()}
        for i, f, p in _necesidades_reales():
            recuperados = rag.recuperar(p, k=3, motor="embeddings")
            self.assertTrue(recuperados, f"{i}: nada por encima del umbral")
            self.assertEqual(recuperados[0][0]["familia"][0], f, i)

    def test_pregunta_ajena_no_recibe_ejemplos(self):
        if not _ollama_embeddings_disponible():
            self.skipTest("Ollama / nomic-embed-text no disponible")
        self.assertEqual(rag.recuperar("¿Cómo se prepara un ceviche peruano?", motor="embeddings"), [])

    def test_sin_ollama_cae_a_tfidf(self):
        with mock.patch.object(rag, "_embed", side_effect=requests.ConnectionError("caído")):
            rag._vector_consulta.cache_clear()
            r = rag.recuperar("¿Qué vendedores cancelan más pedidos?", motor="embeddings")
        rag._vector_consulta.cache_clear()
        self.assertTrue(r)


class TestHarness(unittest.TestCase):
    def test_harness_reintenta_hasta_5_con_verificador_sin_oraculo(self):
        from llm import harness

        c = _Guion(juez='{"tiene_sentido": false, "motivo": "no filtra lo pedido"}')
        with mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1), mock.patch.object(rag, "MOTOR_POR_DEFECTO", "tfidf"):
            r = t.answer_question("¿Cuántos pedidos hay en total?", client=c, usar_plantillas=False, modo="harness")
        self.assertEqual(r.intentos, harness.N_INTENTOS_HARNESS)
        self.assertEqual(len(c.prompts_sql), 5)
        self.assertIn("Un revisor indica", c.prompts_sql[1])
        self.assertEqual(r.modo, "harness")

    def test_harness_acepta_al_primer_intento_si_el_verificador_aprueba(self):
        c = _Guion()
        with mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1), mock.patch.object(rag, "MOTOR_POR_DEFECTO", "tfidf"):
            r = t.answer_question("¿Cuántos pedidos hay en total?", client=c, usar_plantillas=False, modo="harness")
        self.assertEqual(r.intentos, 1)

    def test_verificador_rechaza_porcentaje_imposible(self):
        from llm import harness

        verificar = harness.verificador_sin_oraculo(_Guion(), "¿Qué porcentaje...?")
        ok, pista = verificar("SELECT 1", ["pct_algo"], [[150.0]])
        self.assertFalse(ok)
        self.assertIn("mayores que 100", pista)

    def test_registro_por_intento_con_cliente_medido(self):
        from llm import harness

        class _Detallado(_Guion):
            def generate_detallado(self, prompt, system=None, **kw):
                return {"response": self.generate(prompt, system=system), "prompt_eval_count": 123, "eval_count": 7}

        medido = harness.ClienteMedido(_Detallado(), seed=1)
        with mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1):
            r = t.answer_question("¿Cuántos pedidos hay en total?", client=medido, usar_plantillas=False, modo="fewshot")
        reg = harness.registro_por_intento(r, medido)
        self.assertEqual(reg[0]["tokens_prompt"], 123)
        self.assertEqual(reg[0]["ejemplos_usados"], [e["id"] for e in r.ejemplos_usados])
        self.assertGreaterEqual(medido.resumen()["llamadas_sql"], 1)


if __name__ == "__main__":
    unittest.main()
