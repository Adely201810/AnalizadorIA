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


class _ClienteFalso:
    num_ctx = 8192

    def __init__(self, model, respuesta):
        self.model, self.respuesta, self.llamadas = model, respuesta, []

    def contar_tokens(self, texto, keep_alive=None):
        return len(texto) // 4

    def generate_detallado(self, prompt, system=None, **kw):
        self.llamadas.append({"prompt": prompt, **kw})
        return {"response": self.respuesta(prompt, kw), "prompt_eval_count": 10}


class TestRonda2(unittest.TestCase):
    def test_normalizar_ignora_espacios_mayusculas_y_alias(self):
        a = "SELECT COUNT(*) AS n FROM orders o WHERE o.order_status = 'x';"
        b = "select  count(*) as total from orders AS z where z.order_status='x'"
        self.assertEqual(juez.normalizar_sql(a), juez.normalizar_sql(b))
        self.assertNotEqual(juez.normalizar_sql(a), juez.normalizar_sql(a.replace("'x'", "'y'")))

    def test_sin_flags_el_ciclo_es_el_de_la_ronda_1(self):
        cand = _ClienteFalso("c", lambda p, kw: json.dumps({"sql": "SELECT COUNT(*) AS x FROM sellers"}))
        reg = juez.resolver_con_juez(_caso("n06"), cand, max_iter=3, sintetizar=False)
        self.assertEqual(len(cand.llamadas), 3)
        self.assertTrue(all(ll["temperature"] == 0.0 and ll["seed"] == 42 for ll in cand.llamadas))
        self.assertEqual([i["remuestreos"] for i in reg["intentos"]], [0, 0, 0])

    def test_antirrepeticion_remuestrea_sin_gastar_intento(self):
        # Repite siempre el mismo SQL: cada reintento remuestrea 3 veces y luego lo acepta.
        cand = _ClienteFalso("c", lambda p, kw: json.dumps({"sql": "SELECT COUNT(*) AS x FROM sellers"}))
        reg = juez.resolver_con_juez(_caso("n06"), cand, max_iter=3, sintetizar=False, reintento_temp=0.5)
        self.assertEqual(reg["intentos_usados"], 3)
        self.assertEqual([i["remuestreos"] for i in reg["intentos"]], [0, 3, 3])
        self.assertEqual(len(cand.llamadas), 1 + 4 + 4)
        reintentos = cand.llamadas[1:]
        self.assertTrue(all(ll["temperature"] == 0.5 for ll in reintentos))
        self.assertEqual(len({ll["seed"] for ll in reintentos}), len(reintentos))  # semillas distintas
        self.assertEqual(cand.llamadas[0]["temperature"], 0.0)

    def test_antirrepeticion_acepta_un_sql_nuevo_al_primer_remuestreo(self):
        sqls = iter(["SELECT 1 AS a FROM sellers", "SELECT 1 AS b FROM sellers", "SELECT 2 AS c FROM sellers"])
        cand = _ClienteFalso("c", lambda p, kw: json.dumps({"sql": next(sqls)}))
        reg = juez.resolver_con_juez(_caso("n06"), cand, max_iter=2, sintetizar=False, reintento_temp=0.5)
        self.assertEqual([i["remuestreos"] for i in reg["intentos"]], [0, 1])
        self.assertFalse(reg["intentos"][1]["sql_repetido"])

    def test_reparacion_usa_columnas_reales_y_ruta(self):
        ejec = juez.ejecutar_sql_candidato("SELECT p.payment_installments FROM products p")
        rep = juez.reparar_con_esquema(ejec)
        self.assertIn("products → order_items (por product_id) → order_payments (por order_id)", rep)
        self.assertIn("product_weight_g", rep)  # leída de la base, no escrita a mano

    def test_reparacion_con_error_de_sqlite(self):
        ejec = juez.ejecutar_sql_candidato("SELECT review_score FROM vw_retraso_por_rango")
        self.assertEqual(ejec["etapa"], "ejecucion")
        rep = juez.reparar_con_esquema(ejec)
        self.assertIn("columnas reales de vw_retraso_por_rango", rep)
        self.assertIn("order_reviews", rep)

    def test_la_reparacion_nunca_revela_la_respuesta(self):
        sqls = ["SELECT review_score FROM vw_retraso_por_rango",
                "SELECT s.seller_id FROM vw_entregas_retrasos s",
                "SELECT t.payment_installments FROM products t",
                "SELECT product_category_name_english FROM vw_ventas_pedido",
                "SELECT x FROM tabla_que_no_existe"]
        for sql in sqls:
            rep = juez.reparar_con_esquema(juez.ejecutar_sql_candidato(sql))
            self.assertTrue(rep, sql)
            for caso in CASOS.values():
                self.assertEqual(juez.detectar_fuga(rep, caso), [], (sql, caso["id"]))

    def test_modo_edicion_y_pistas_v2_sin_fugas(self):
        cand = _ClienteFalso("c", lambda p, kw: json.dumps({"sql": "SELECT p.order_id FROM products p"}))
        for caso in CASOS.values():
            cand.llamadas.clear()
            reg = juez.resolver_con_juez(caso, cand, max_iter=3, sintetizar=False, reintento_temp=0.5,
                                         reparar_esquema=True, modo_edicion=True, pistas_v2=True)
            self.assertIn("Corrígelo cambiando SOLO lo necesario", cand.llamadas[-1]["prompt"])
            self.assertIn("Reparación con el esquema real", reg["intentos"][0]["retroalimentacion"]["texto"])
            for ll in cand.llamadas:
                sin_sql_propio = re.sub(r"```sql.*?```", "", ll["prompt"], flags=re.S)
                self.assertEqual(juez.detectar_fuga(sin_sql_propio, caso), [])
                self.assertNotIn(caso["sql_referencia"], ll["prompt"])

    def test_pistas_v2_empiezan_en_concepto(self):
        caso = _caso("n06")
        ejec = juez.ejecutar_sql_candidato("SELECT COUNT(*) AS x FROM order_items")
        diag = juez.diagnosticar_intento(caso, ejec)
        self.assertEqual(juez.retroalimentar("plantilla", caso, ejec, diag, 1, None, 1, None)["nivel"], 1)
        r = juez.retroalimentar("plantilla", caso, ejec, diag, 1, None, 1, None, pistas_v2=True)
        self.assertEqual(r["nivel"], 2)
        self.assertIn("Posible causa", r["texto"])

    def test_texto_confiable_acepta_umbrales_de_la_pregunta_solo_si_se_pide(self):
        from llm.text_to_sql import _respuesta_respaldada_por_datos

        texto = "Con ingresos de al menos R$ 5,000, la primera es christmas_supplies con 36.66%."
        filas = [("christmas_supplies", 36.66)]
        self.assertFalse(_respuesta_respaldada_por_datos(texto, filas))  # comportamiento del chat, igual
        self.assertTrue(_respuesta_respaldada_por_datos(texto, filas, numeros_extra=[5000.0]))

    def test_patron_validos_no_se_activa_con_vistas_que_ya_filtran(self):
        caso = _caso("n04")
        patron = next(p for p in caso["patrones_error"] if p["diagnostico"].startswith("No filtra pedidos válidos"))
        self.assertIsNone(re.search(patron["regex"], "SELECT seller_id, ingresos FROM vw_ingresos_por_vendedor", re.I))
        self.assertIsNotNone(re.search(patron["regex"], "SELECT seller_id, SUM(price) FROM order_items GROUP BY 1", re.I))


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
