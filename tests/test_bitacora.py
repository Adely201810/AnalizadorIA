"""
Fase 10: bitácora persistente de errores de esquema y juez de sensatez en el
chat libre. Cliente guionado (sin Ollama); validadores, SQLite (solo lectura)
y bitácora en un archivo temporal son el código real.

Uso: python -m unittest tests.test_bitacora -v
"""
import tempfile
import unittest
from pathlib import Path

from llm.bitacora import BitacoraEsquema
from llm.juez import JuezLLM, texto_revision
from llm.text_to_sql import answer_question

DB = Path(__file__).resolve().parent.parent / "db" / "olist.db"
SQL_COL_CALIFICADA = "```sql\nSELECT o.customer_state, COUNT(*) FROM orders o GROUP BY o.customer_state\n```"
SQL_COL_SUELTA = "```sql\nSELECT customer_state, COUNT(*) FROM orders GROUP BY customer_state\n```"
SQL_BIEN = ("```sql\nSELECT c.customer_state, COUNT(*) AS pedidos FROM orders o JOIN customers c "
            "ON c.customer_id = o.customer_id GROUP BY c.customer_state ORDER BY pedidos DESC LIMIT 1\n```")


class ClienteGuionado:
    model, host, temperature, num_ctx = "guionado", "-", 0.0, 0

    def __init__(self, guion):
        self.guion, self.prompts = list(guion), []

    def generate(self, prompt, system=None, **kwargs):
        self.prompts.append((system or "", prompt))
        return self.guion.pop(0)


def _prompts_sql(cliente):
    return [pr for sy, pr in cliente.prompts if "generador de consultas SQL" in sy]


class TestBitacora(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bitacora = BitacoraEsquema(Path(self.tmp.name) / "bitacora.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_registra_error_y_lo_usa_en_una_pregunta_distinta_posterior(self):
        mtime_db = DB.stat().st_mtime_ns
        # 1) Pregunta A: el modelo usa orders.customer_state (no existe) dos veces.
        c1 = ClienteGuionado(["UNA", SQL_COL_CALIFICADA, SQL_COL_CALIFICADA])
        r1 = answer_question("¿Cuál es el estado con más pedidos entregados?", client=c1,
                             usar_plantillas=False, bitacora=self.bitacora)
        self.assertEqual([d["tipo"] for d in r1.intentos_detalle], ["ejecucion", "ejecucion"])
        entradas = self.bitacora.entradas()
        self.assertEqual([e["clave"] for e in entradas], ["columna:orders.customer_state"])
        self.assertEqual(entradas[0]["veces"], 2)
        self.assertIn("customers", entradas[0]["mensaje"])  # la corrección dice dónde está la columna
        # La primera pregunta no tenía nada que recordar.
        self.assertNotIn("Errores de esquema", _prompts_sql(c1)[0])

        # 2) Pregunta B (distinta): el prompt ya trae la corrección y el modelo la sigue.
        c2 = ClienteGuionado(["UNA", SQL_BIEN, "SP lidera."])
        r2 = answer_question("¿Qué estado tiene más pedidos?", client=c2, usar_plantillas=False, bitacora=self.bitacora)
        primer_prompt = _prompts_sql(c2)[0]
        self.assertIn("Errores de esquema cometidos en consultas anteriores", primer_prompt)
        self.assertIn("La columna 'customer_state' no existe en 'orders'", primer_prompt)
        self.assertEqual([d["tipo"] for d in r2.intentos_detalle], ["ok"])
        self.assertEqual(self.bitacora.entradas()[0]["veces"], 2)  # B no repitió el error
        # La bitácora nunca toca la base de Olist.
        self.assertEqual(DB.stat().st_mtime_ns, mtime_db)
        self.assertNotEqual(self.bitacora.ruta.resolve().parent, DB.resolve().parent)

    def test_error_de_sqlite_sin_calificar(self):
        c = ClienteGuionado(["UNA", SQL_COL_SUELTA, SQL_COL_SUELTA])
        answer_question("¿Cuántos pedidos hay por estado?", client=c, usar_plantillas=False, bitacora=self.bitacora)
        e = self.bitacora.entradas()[0]
        self.assertEqual(e["clave"], "columna:*.customer_state")
        self.assertIn("customers", e["mensaje"])

    def test_select_sin_from_se_diagnostica_como_tal(self):
        # Etapa 2, Paso 4: SQL real de llama3.1 (n01, repetido 39 veces en DESARROLLO).
        sin_from = ("```sql\nSELECT ROUND(100.0 * COUNT(DISTINCT customer_unique_id) / "
                    "(SELECT COUNT(DISTINCT customer_unique_id) FROM customers), 2) AS pct\n```")
        c = ClienteGuionado(["UNA", sin_from, sin_from])
        r = answer_question("¿Qué parte de los clientes compró dos veces?", client=c,
                            usar_plantillas=False, bitacora=self.bitacora)
        self.assertIn("no such column: customer_unique_id", r.intentos_detalle[0]["detalle"])
        e = self.bitacora.entradas()
        self.assertEqual([x["clave"] for x in e], ["select_sin_from"])  # antes: "columna:*.customer_unique_id"
        self.assertEqual(e[0]["veces"], 2)
        self.assertIn("sin FROM", e[0]["mensaje"])
        self.assertTrue(e[0]["mensaje"].endswith("FROM t2)."))  # cabe entero en MAX_CHARS_ENTRADA
        self.assertIn("El SELECT principal usó 'customer_unique_id' sin FROM", self.bitacora.texto_para_prompt())

    def test_from_entre_parentesis(self):
        mal = "```sql\nSELECT ROUND(AVG(review_score) FROM order_reviews) AS x\n```"
        c = ClienteGuionado(["UNA", mal, mal])
        answer_question("¿Calificación media?", client=c, usar_plantillas=False, bitacora=self.bitacora)
        self.assertEqual([x["clave"] for x in self.bitacora.entradas()], ["from_entre_parentesis"])

    def test_limites(self):
        b = BitacoraEsquema(Path(self.tmp.name) / "lim.json", max_entradas=3, max_inyectadas=2)
        for i in range(5):
            b.registrar([{"tipo": "tabla", "nombre": f"tabla_{i}"}], "p")
        self.assertEqual(len(b.entradas()), 3)
        texto = b.texto_para_prompt()
        self.assertEqual(texto.count("\n- "), 2)
        chica = BitacoraEsquema(Path(self.tmp.name) / "chica.json", max_bytes=600)
        for i in range(20):
            chica.registrar([{"tipo": "tabla", "nombre": f"t{i}"}], "pregunta " * 10)
        self.assertLessEqual(len(chica.ruta.read_bytes()), 600)


class TestSensatezChat(unittest.TestCase):
    def test_revision_del_juez_y_texto_no_dice_verificado(self):
        juez = JuezLLM(ClienteGuionado(['{"tiene_sentido": false, "motivo": "cuenta pedidos cancelados"}']))
        c = ClienteGuionado(["UNA", SQL_BIEN, "SP lidera."])
        r = answer_question("¿Qué estado tiene más pedidos válidos?", client=c, usar_plantillas=False, juez_sensatez=juez)
        self.assertEqual(r.revision_sensatez, {"tiene_sentido": False, "motivo": "cuenta pedidos cancelados"})
        texto = texto_revision(r.revision_sensatez)
        self.assertIn("no comprueba que la cifra sea correcta", texto)
        self.assertNotIn("verificad", texto.lower())

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
