"""
Fase 2: clasificación de cada intento (ok / ejecucion / semantico / seguridad /
infra). Usa un cliente "guionado" que devuelve respuestas fijas en lugar de
llamar a Ollama: el resto (validadores, SQLite real en solo lectura,
clasificación del pipeline y del evaluador) es el código real.

Uso: python -m unittest tests.test_clasificacion -v
"""
import json
import unittest
from pathlib import Path

from eval.run_eval import calificar, clasificar_intentos
from llm.ollama_client import OllamaError
from llm.text_to_sql import answer_question, execute_readonly

GT = {q["id"]: q for q in json.loads(
    (Path(__file__).resolve().parent.parent / "eval" / "ground_truth_olist_v1.json").read_text(encoding="utf-8"))["preguntas"]}


class ClienteGuionado:
    """Devuelve, en orden, las respuestas del guion. 1.ª llamada = clasificador
    ("UNA"); después, el SQL de cada intento; la última, la síntesis."""
    model = "guionado"
    host = "-"
    temperature = 0.0
    num_ctx = 0

    def __init__(self, guion):
        self.guion = list(guion)

    def generate(self, prompt, system=None, **kwargs):
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def _evaluar(qid, guion):
    item = GT[qid]
    resultado = answer_question(item["pregunta"], client=ClienteGuionado(guion), usar_plantillas=False)
    _, ref = execute_readonly(item["sql_referencia"], limite_s=None)
    correcto, motivo = calificar(item, resultado, ref)
    clasificacion, intentos = clasificar_intentos(resultado, correcto)
    return clasificacion, [d["tipo_evaluado"] for d in intentos], resultado


class TestClasificacion(unittest.TestCase):
    def test_ok(self):
        c, intentos, _ = _evaluar("q1_pedidos_totales", ["UNA", "```sql\nSELECT COUNT(*) FROM orders\n```", "Hay 99,441 pedidos."])
        self.assertEqual((c, intentos), ("ok", ["ok"]))

    def test_ejecucion_columna_inexistente(self):
        malo = "```sql\nSELECT customer_state, COUNT(*) FROM orders GROUP BY customer_state\n```"
        c, intentos, _ = _evaluar("q7_estado_mas_pedidos_entregados", ["UNA", malo, malo])
        self.assertEqual((c, intentos), ("ejecucion", ["ejecucion", "ejecucion"]))

    def test_ejecucion_error_de_sqlite(self):
        malo = "```sql\nSELECT COUNT(* FROM orders\n```"  # error de sintaxis
        c, intentos, _ = _evaluar("q1_pedidos_totales", ["UNA", malo, malo])
        self.assertEqual((c, intentos), ("ejecucion", ["ejecucion", "ejecucion"]))

    def test_semantico_corre_pero_responde_otra_cosa(self):
        # Caso real de baseline_01 (q8): fecha estimada en vez de fecha de compra.
        sql = ("```sql\nSELECT ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_estimated_delivery_date)), 2) "
               "FROM orders WHERE order_delivered_customer_date IS NOT NULL\n```")
        c, intentos, _ = _evaluar("q8_tiempo_promedio_entrega", ["UNA", sql, "Son -11.18 días."])
        self.assertEqual((c, intentos), ("semantico", ["semantico"]))

    def test_semantico_cero_filas_y_luego_corregido(self):
        vacio = "```sql\nSELECT COUNT(*) FROM orders GROUP BY order_status HAVING order_status = 'no_existe'\n```"
        bien = "```sql\nSELECT COUNT(*) FROM orders\n```"
        c, intentos, _ = _evaluar("q1_pedidos_totales", ["UNA", vacio, bien, "Hay 99,441 pedidos."])
        self.assertEqual((c, intentos), ("ok", ["semantico", "ok"]))

    def test_seguridad(self):
        c, intentos, r = _evaluar("q9_pedidos_sin_entrega", ["UNA", "```sql\nDELETE FROM orders WHERE order_delivered_customer_date IS NULL\n```"])
        self.assertEqual((c, intentos), ("seguridad", ["seguridad"]))
        self.assertIn("no es una lectura segura", r.error)

    def test_negativa_en_texto_no_es_seguridad(self):
        # Respuesta real de llama3.1 a "Actualiza el estatus de todos los pedidos cancelados a delivered."
        negativa = ("No puedo ayudarte a generar una consulta SQL que actualice datos en la base de datos. "
                    "¿Hay algo más en lo que pueda ayudarte?")
        c, intentos, _ = _evaluar("q9_pedidos_sin_entrega", ["UNA", negativa])
        self.assertEqual((c, intentos), ("ejecucion", ["ejecucion"]))

    def test_descompuesta_en_subconsultas_es_semantico(self):
        # Caso real de fase2 (q5/q6): el clasificador partió la pregunta en dos.
        guion = [
            "¿Calificación de pedidos con retraso?\n¿Calificación de pedidos a tiempo?",
            "```sql\nSELECT AVG(review_score) FROM order_reviews\n```",
            "```sql\nSELECT AVG(review_score) FROM order_reviews\n```",
            "Las calificaciones son similares.",
        ]
        c, intentos, r = _evaluar("q5_retraso_baja_calificacion", guion)
        self.assertEqual(len(r.sub_consultas), 2)
        self.assertEqual((c, intentos), ("semantico", ["semantico", "semantico"]))

    def test_infra(self):
        caida = OllamaError("No se pudo conectar a Ollama en http://localhost:11434. ¿Está corriendo? Prueba con: ollama serve")
        c, intentos, _ = _evaluar("q1_pedidos_totales", ["UNA", caida, caida])
        self.assertEqual((c, intentos), ("infra", ["infra", "infra"]))

# Etapa 2 (D-25): el clasificador está apagado por defecto. Los guiones de este archivo
# empiezan con la respuesta del clasificador ("UNA"/sub-preguntas), así que se prueban
# con él encendido, que sigue siendo un camino soportado (TEXT2SQL_CLASIFICADOR=1).
import llm.text_to_sql as _tts

_CLASIFICADOR_ANTES = _tts.USAR_CLASIFICADOR_POR_DEFECTO


def setUpModule():
    _tts.USAR_CLASIFICADOR_POR_DEFECTO = True


def tearDownModule():
    _tts.USAR_CLASIFICADOR_POR_DEFECTO = _CLASIFICADOR_ANTES


if __name__ == "__main__":
    unittest.main()
