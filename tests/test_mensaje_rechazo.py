"""
Etapa 2, Paso 4: el chat distingue un rechazo de SEGURIDAD (el modelo generó SQL
que no es una lectura permitida) de una NEGATIVA DEL MODELO (contestó con texto
en vez de SQL) y de un fallo de infraestructura. Antes, la negativa se mostraba
como "La consulta generada no es una lectura segura y fue rechazada".

Configuración por defecto (sin clasificador): la 1.ª llamada al modelo ya es el SQL.

Uso: python -m unittest tests.test_mensaje_rechazo -v
"""
import unittest

from llm.ollama_client import OllamaError
from llm.text_to_sql import MENSAJES_ERROR_CHAT, answer_question


class ClienteGuionado:
    model = "guionado"
    host = "-"
    temperature = 0.0
    num_ctx = 0

    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = 0

    def generate(self, prompt, system=None, **kwargs):
        self.llamadas += 1
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def _preguntar(guion):
    cliente = ClienteGuionado(guion)
    r = answer_question("¿Cuántos pedidos hay sin fecha de entrega?", client=cliente,
                        usar_plantillas=False, usar_clasificador=False)
    return r, cliente


class TestMensajeRechazo(unittest.TestCase):
    def test_negativa_del_modelo(self):
        negativa = "No puedo ayudarte a modificar datos.\n¿Hay algo más en lo que pueda ayudarte?"
        r, cliente = _preguntar([negativa])
        self.assertEqual(r.tipo_error, "negativa_modelo")
        self.assertEqual(r.error, "El modelo no generó una consulta SQL; respondió con texto: "
                                  "«No puedo ayudarte a modificar datos. ¿Hay algo más en lo que pueda ayudarte?»")
        self.assertNotIn("segura", r.error)
        self.assertNotIn("segura", MENSAJES_ERROR_CHAT[r.tipo_error])
        self.assertEqual(cliente.llamadas, 1)  # mismo flujo que antes: corta sin reintentar
        self.assertEqual(r.filas, [])

    def test_negativa_larga_se_recorta(self):
        r, _ = _preguntar(["No " * 200])
        self.assertTrue(r.error.endswith("…»"))
        self.assertLess(len(r.error), 300)

    def test_rechazo_de_seguridad(self):
        r, cliente = _preguntar(["```sql\nDELETE FROM orders WHERE order_delivered_customer_date IS NULL\n```"])
        self.assertEqual(r.tipo_error, "seguridad")
        self.assertIn("no es una lectura segura", r.error)
        self.assertIn("No se ejecutó nada", MENSAJES_ERROR_CHAT["seguridad"])
        self.assertEqual(cliente.llamadas, 1)

    def test_infra(self):
        caida = OllamaError("No se pudo conectar a Ollama en http://localhost:11434.")
        r, _ = _preguntar([caida, caida])
        self.assertEqual(r.tipo_error, "infra")
        self.assertIn("Ollama", MENSAJES_ERROR_CHAT["infra"])

    def test_los_tres_mensajes_son_distintos(self):
        self.assertEqual(len(set(MENSAJES_ERROR_CHAT.values())), 3)


if __name__ == "__main__":
    unittest.main()
