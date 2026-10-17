"""
Juez iterativo (D-34): veredicto determinista, filtro anti-fuga, guarda de contexto y la
garantía central: el SQL de referencia, las cifras esperadas y la respuesta de referencia
NUNCA llegan al prompt del modelo candidato.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from llm import juez
from llm.ollama_client import ContextoInsuficienteError, verificar_margen_contexto

RAIZ = Path(__file__).resolve().parent.parent
CASOS = {c["id"]: c for c in json.loads((RAIZ / "eval" / "casos_juez.json").read_text(encoding="utf-8"))["casos"]}


def _caso(prefijo: str) -> dict:
    return next(c for k, c in CASOS.items() if k.startswith(prefijo))


class TestVeredicto(unittest.TestCase):
    def test_la_referencia_cumple_su_propio_criterio(self):
        for cid, caso in CASOS.items():
            with self.subTest(caso=cid):
                v = juez.veredicto_caso(caso, caso["resultado_referencia"]["filas"])
                self.assertTrue(v["correcto"], v)

    def test_columnas_y_orden_de_columnas_no_importan(self):
        caso = _caso("n06")
        self.assertTrue(juez.veredicto_caso(caso, [[79.0055, "COMPUTERS ", 181, "x"]])["correcto"])

    def test_variantes_erroneas_medidas_fallan(self):
        # Valores reales de las trampas medidas al construir los casos (D-32).
        self.assertFalse(juez.veredicto_caso(_caso("n06"), [["computers", 203, 78.82]])["correcto"])  # por artículo
        self.assertFalse(juez.veredicto_caso(_caso("n02"), [["1-3", 2651, 19.12, 9.23]])["correcto"])  # reseñas crudas
        self.assertFalse(juez.veredicto_caso(_caso("n04"), [[14, 597265.18]])["correcto"])  # reseñas crudas
        self.assertFalse(juez.veredicto_caso(_caso("c01"), [[98207]])["correcto"])  # solo válidos
        n05_avg = [["electronics", 68.55], ["christmas_supplies", 67.61], ["fashion_underwear_beach", 56.55]]
        self.assertFalse(juez.veredicto_caso(_caso("n05"), n05_avg)["correcto"])  # AVG de razones

    def test_fila_primera_exige_orden(self):
        caso = _caso("n06")
        self.assertFalse(juez.veredicto_caso(caso, [["watches_gifts", 67.45], ["computers", 79.01]])["correcto"])

    def test_conjunto_igual_sin_orden_y_sin_extras(self):
        caso = _caso("n08")
        filas = [[c] for c in reversed(caso["criterio_aceptacion"]["comprobaciones"][0]["valores"])]
        self.assertTrue(juez.veredicto_caso(caso, filas)["correcto"])
        self.assertFalse(juez.veredicto_caso(caso, filas + [["audio"]])["correcto"])
        self.assertFalse(juez.veredicto_caso(caso, filas[1:])["correcto"])

    def test_sin_filas_es_incorrecto(self):
        for caso in CASOS.values():
            self.assertFalse(juez.veredicto_caso(caso, [])["correcto"])


class TestFiltroAntiFuga(unittest.TestCase):
    def test_bloquea_cifras_esperadas_incluso_redondeadas(self):
        caso = _caso("n02")
        self.assertTrue(juez.detectar_fuga("El porcentaje correcto es 19.08 %.", caso))
        self.assertTrue(juez.detectar_fuga("Deberías obtener cerca de 19.1 %.", caso))
        self.assertTrue(juez.detectar_fuga("Son 2,636 pedidos.", caso))
        self.assertTrue(juez.detectar_fuga("a tiempo es 9.19", caso))
        self.assertTrue(juez.detectar_fuga("suman R$ 574,541.26", _caso("n04")))
        self.assertTrue(juez.detectar_fuga("Te deberían salir 13 vendedores.", _caso("n04")))

    def test_bloquea_valores_de_texto_esperados(self):
        self.assertTrue(juez.detectar_fuga("La respuesta es Computers.", _caso("n06")))
        self.assertTrue(juez.detectar_fuga("falta christmas_supplies", _caso("n05")))

    def test_no_confunde_palabras_que_contienen_un_valor(self):
        # "art" es una categoría esperada en n08; "artículos" no debe bloquearse.
        self.assertEqual(juez.detectar_fuga("Cuenta pedidos, no artículos.", _caso("n08")), [])

    def test_bloquea_fragmentos_largos_del_sql_de_referencia(self):
        caso = _caso("n05")
        fragmento = "ROUND(100.0 * SUM(freight_value) / NULLIF(SUM(price), 0), 2)"
        self.assertTrue(juez.detectar_fuga(f"Usa {fragmento}", caso))
        self.assertTrue(juez.detectar_fuga(caso["sql_referencia"], caso))

    def test_permite_pistas_conceptuales_y_umbrales_de_la_pregunta(self):
        caso = _caso("n04")
        texto = ("Agrega primero por vendedor: un pedido con varios artículos se cuenta una sola vez con "
                 "COUNT(DISTINCT order_id). El mínimo es de 30 pedidos y la calificación debe ser menor a 3.5; "
                 "usa 100.0 * a / b para el porcentaje.")
        self.assertEqual(juez.detectar_fuga(texto, caso), [])

    def test_la_plantilla_nunca_revela(self):
        for caso in CASOS.values():
            diag = {"error": None, "forma": ["La consulta devolvió más filas de las que pide la pregunta."],
                    "patrones": [p["diagnostico"] for p in caso["patrones_error"]], "sanidad": []}
            for nivel in (1, 2, 3):
                with self.subTest(caso=caso["id"], nivel=nivel):
                    self.assertEqual(juez.detectar_fuga(juez.retro_plantilla(diag, nivel), caso), [])

    def test_retroalimentar_sustituye_una_pista_que_revela(self):
        caso = _caso("n06")

        class JuezFiltrador:
            model = "falso"

            def generate_detallado(self, *a, **k):
                return {"response": "La categoría correcta es computers con 79.01 %."}

        ejec = {"ok": True, "sql": "SELECT 1", "columnas": ["x"], "filas": [[1]], "etapa": None, "error": None}
        diag = juez.diagnosticar_intento(caso, ejec)
        r = juez.retroalimentar("llm", caso, ejec, diag, 3, JuezFiltrador(), 1, None)
        self.assertEqual(juez.detectar_fuga(r["texto"], caso), [])
        self.assertTrue(r["fallback_plantilla"])
        self.assertGreaterEqual(r["fugas_bloqueadas"], 2)


class TestPromptCandidatoSinReferencia(unittest.TestCase):
    """Corre el ciclo completo con modelos falsos: el candidato siempre falla y el juez intenta
    filtrar la respuesta en cada pista. Ningún prompt del candidato puede contener nada de la
    referencia."""

    def test_ningun_prompt_del_candidato_contiene_la_referencia(self):
        class Falso:
            num_ctx = 8192

            def __init__(self, model, respuesta):
                self.model, self.respuesta, self.prompts = model, respuesta, []

            def contar_tokens(self, texto, keep_alive=None):
                return len(texto) // 4

            def generate_detallado(self, prompt, system=None, **kw):
                self.prompts.append(prompt)
                return {"response": self.respuesta(prompt), "prompt_eval_count": 10}

        for cid, caso in CASOS.items():
            with self.subTest(caso=cid):
                fuga = (f"La respuesta es {caso['respuesta_nl_referencia']} Usa esto: {caso['sql_referencia']}")
                juez_falso = Falso("juez", lambda p, f=fuga: f)
                candidato = Falso("candidato", lambda p: json.dumps({"sql": "SELECT COUNT(*) AS x FROM sellers"}))
                for modo in ("llm", "plantilla"):
                    candidato.prompts.clear()
                    reg = juez.resolver_con_juez(caso, candidato, max_iter=4, feedback=modo,
                                                 juez_client=juez_falso, sintetizar=False)
                    self.assertEqual(len(candidato.prompts), 4)
                    for prompt in candidato.prompts:
                        self.assertNotIn(caso["sql_referencia"], prompt)
                        self.assertNotIn(caso["respuesta_nl_referencia"], prompt)
                        # El SQL anterior es texto del PROPIO candidato (puede compartir 6 tokens
                        # genéricos con la referencia, p. ej. "SELECT COUNT(*) AS"); lo demás no.
                        sin_sql_propio = re.sub(r"```sql.*?```", "", prompt, flags=re.S)
                        self.assertEqual(juez.detectar_fuga(sin_sql_propio, caso), [], prompt)
                    if modo == "llm":
                        self.assertGreater(reg["fugas_bloqueadas"], 0)


class TestGuardaContexto(unittest.TestCase):
    def test_corta_si_no_deja_margen(self):
        verificar_margen_contexto(6000, 600, 8192)  # 6600 <= 7372.8
        with self.assertRaises(ContextoInsuficienteError):
            verificar_margen_contexto(6900, 600, 8192)

    def test_extraer_sql_json(self):
        self.assertEqual(juez.extraer_sql_json('{"sql": "SELECT 1"}'), "SELECT 1")
        self.assertEqual(juez.extraer_sql_json('{"sql": "```sql\\nSELECT 2\\n```"}'), "SELECT 2")
        self.assertEqual(juez.extraer_sql_json('{"sql": "SELECT \'a\'" '), "SELECT 'a'")


if __name__ == "__main__":
    unittest.main()
