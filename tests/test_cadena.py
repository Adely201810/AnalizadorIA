"""
Fases 6, 9 y 7: N intentos reales, corte en el primer ACIERTO y pistas sin
fugas del valor de referencia. Cliente guionado (sin Ollama); validadores,
SQLite (solo lectura), árbitro y guarda de pistas son el código real.

Uso: python -m unittest tests.test_cadena -v
"""
import json
import unittest
from pathlib import Path

from eval.pistas import censurar, formas_de_valor, fugas, valores_de_referencia
from eval.run_eval import crear_verificador
from llm.juez import JuezLLM
from llm.text_to_sql import answer_question, execute_readonly

GT = {q["id"]: q for q in json.loads(
    (Path(__file__).resolve().parent.parent / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]}
N01 = GT["n01_pct_clientes_recurrentes"]  # referencia: 3.04

SQL_ROTO = "```sql\nSELECT COUNT(* FROM orders\n```"
SQL_MAL = "```sql\nSELECT ROUND(100.0 * AVG(es_recurrente), 2) FROM vw_clientes_recurrentes WHERE es_recurrente = 1\n```"  # 100.0
SQL_BIEN = ("```sql\nSELECT ROUND(100.0 * SUM(CASE WHEN num_pedidos > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) "
            "FROM vw_clientes_recurrentes\n```")  # 3.04


class ClienteGuionado:
    model, host, temperature, num_ctx = "guionado", "-", 0.0, 0

    def __init__(self, guion):
        self.guion = list(guion)
        self.prompts = []  # (system, prompt) de cada llamada

    def generate(self, prompt, system=None, **kwargs):
        self.prompts.append((system or "", prompt))
        return self.guion.pop(0)


def _preguntar(guion, n, verificador=None):
    cliente = ClienteGuionado(["UNA"] + guion)
    r = answer_question(N01["pregunta"], client=cliente, n_intentos=n, usar_plantillas=False, verificador=verificador)
    return r, cliente


class TestNIntentos(unittest.TestCase):
    """Fase 6: N controla de verdad el número de intentos (antes, max_retries=2
    permitía como máximo 2 intentos por la bandera ya_reintento_por_problema)."""

    def test_n_intentos_con_errores(self):
        for n in (1, 2, 3, 5):
            r, cliente = _preguntar([SQL_ROTO] * n, n)
            self.assertEqual(r.intentos, n)
            self.assertEqual(len(r.intentos_detalle), n)
            self.assertEqual([d["tipo"] for d in r.intentos_detalle], ["ejecucion"] * n)


class TestCorteEnPrimerAcierto(unittest.TestCase):
    """Fase 9."""

    def test_sin_verificador_corta_en_primer_ejecutable(self):
        r, cliente = _preguntar([SQL_MAL, SQL_BIEN, "Resumen."], n=3)
        self.assertEqual(r.intentos, 1)  # se queda con el primer SQL que corre (aunque sea incorrecto)
        self.assertEqual(r.filas, [(100.0,)])

    def test_con_verificador_sigue_hasta_el_acierto_y_corta(self):
        _, ref = execute_readonly(N01["sql_referencia"], limite_s=None)
        registro = {"opiniones_juez": [], "diagnosticos_juez": [], "pistas": []}
        verificador = crear_verificador(N01, ref, "generico", None, registro)
        # guion con 4 SQL posibles: MAL, BIEN, MAL, MAL; debe cortar en el 2.º (primer acierto)
        r, cliente = _preguntar([SQL_MAL, SQL_BIEN, SQL_MAL, SQL_MAL, "Resumen."], n=4, verificador=verificador)
        self.assertEqual(r.intentos, 2)
        self.assertEqual(r.filas, [(3.04,)])
        self.assertEqual([d.get("verificado") for d in r.intentos_detalle], [False, True])
        prompts_sql = [pr for sy, pr in cliente.prompts if "generador de consultas SQL" in sy]
        self.assertEqual(len(prompts_sql), 2)  # se pidieron solo 2 SQL aunque N=4
        self.assertEqual(len(registro["pistas"]), 1)


class TestPistasSinFugas(unittest.TestCase):
    """Fase 7: ningún prompt de reintento contiene el valor de referencia ni derivados evidentes."""

    def test_formas_de_valor(self):
        formas = formas_de_valor(1003862.14)
        for f in ("1003862.14", "1,003,862.14", "1.003.862,14", "1003862", "1,003,862"):
            self.assertIn(f, formas)
        self.assertIn("3.04", formas_de_valor(3.04))
        self.assertIn("3,04", formas_de_valor(3.04))
        self.assertIn("0.030", formas_de_valor(3.04))  # escala fracción

    def test_motivo_con_numero_de_filas_no_se_filtra(self):
        from eval.pistas import construir_pista
        pista = construir_pista("generico", "filas: el modelo devolvió 3, la referencia tiene 5")
        self.assertNotIn("5", pista)
        self.assertNotIn("3", pista)

    def test_juez_que_filtra_el_valor_es_censurado_y_no_llega_al_prompt(self):
        _, ref = execute_readonly(N01["sql_referencia"], limite_s=None)
        # Juez guionado que, a propósito, "filtra" la respuesta correcta en varias formas.
        juez = JuezLLM(ClienteGuionado([
            "Deberías obtener 3.04 (o sea 3,04 %, 0.0304 como fracción): divide entre todos los clientes."
        ]))
        registro = {"opiniones_juez": [], "diagnosticos_juez": [], "pistas": []}
        verificador = crear_verificador(N01, ref, "juez", juez, registro)
        r, cliente = _preguntar([SQL_MAL, SQL_BIEN, "Resumen."], n=3, verificador=verificador)
        self.assertEqual(r.filas, [(3.04,)])
        self.assertTrue(registro["pistas"][0]["formas_censuradas"], "la guarda debió censurar algo")
        valores = valores_de_referencia(ref, N01["tipos_columnas"])
        # Prompts de GENERACIÓN DE SQL (intento 1 y reintentos). La síntesis, posterior
        # al acierto, contiene legítimamente el resultado del propio modelo.
        prompts_sql = [pr for sy, pr in cliente.prompts if "generador de consultas SQL" in sy]
        self.assertEqual(len(prompts_sql), 2)
        for prompt in prompts_sql:
            self.assertEqual(fugas(prompt, valores), [], f"fuga en el prompt: {prompt!r}")
        segundo_prompt = cliente.prompts[2][1]  # [0]=clasificador, [1]=intento 1, [2]=intento 2
        self.assertIn("[valor omitido]", segundo_prompt)
        self.assertIn("Diagnóstico del revisor", segundo_prompt)

    def test_censurar_no_toca_numeros_que_no_son_la_referencia(self):
        texto, censuradas = censurar("Usa los 5 pedidos de 2017 y no 100.0", [3.04])
        self.assertEqual(censuradas, [])
        self.assertEqual(texto, "Usa los 5 pedidos de 2017 y no 100.0")


class TestJuezParseo(unittest.TestCase):
    def test_json_y_basura(self):
        j = JuezLLM(ClienteGuionado([
            'Claro: {"responde": false, "motivo": "promedia sobre los recurrentes"}',
            "no sé",
            '{"tiene_sentido": "true", "motivo": "ok"}',
        ]))
        o = j.opinar("p", "SELECT 1", ["x"], [(1,)])
        self.assertEqual((o.valor, o.motivo), (False, "promedia sobre los recurrentes"))
        self.assertIsNone(j.opinar("p", "SELECT 1", ["x"], [(1,)]).valor)
        self.assertTrue(j.evaluar_sensatez("p", "SELECT 1").valor)


if __name__ == "__main__":
    unittest.main()
