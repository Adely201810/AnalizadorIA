"""
Etapa 3, Paso 3: experimentos de contexto E1-E7 (llm/contexto_e3.py y llm/schema_context.py).

- Con los interruptores apagados (por defecto) nada cambia: sin contexto de usuario extra,
  el esquema no depende de la pregunta y build_schema_context() es el de siempre.
- E1: el glosario solo inyecta las entradas cuyo término aparece en la pregunta, y sus
  fragmentos SQL están lejos de las referencias del oráculo.
- E2: la selección de esquema incluye las tablas puente necesarias para unir.
- E3/E4: las descripciones y vistas nuevas existen en la base.
- E5: el banco tiene >= 30 ejemplos y se eligen 3 por TF-IDF.
- E6: la regla del plan reemplaza exactamente una regla del system prompt.
- E7: la autoconsistencia elige el resultado más frecuente (cliente guionado, sin Ollama).

Uso: python -m unittest tests.test_contexto_e3 -v
"""
import os
import unittest

from eval.similitud import jaccard, preguntas_oraculo, tokens_sql
from llm import contexto_e3 as ctx
from llm import schema_context as sc
from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE, _elegir_por_autoconsistencia


_INTERRUPTORES = ("TEXT2SQL_GLOSARIO", "TEXT2SQL_ESQUEMA_POR_PREGUNTA", "TEXT2SQL_DESC_COLUMNAS", "TEXT2SQL_VISTAS_NEGOCIO",
                  "TEXT2SQL_FEWSHOT_DINAMICO", "TEXT2SQL_PLAN", "TEXT2SQL_AUTOCONSISTENCIA")


@unittest.skipIf(any(os.environ.get(v) for v in _INTERRUPTORES), "algún interruptor de la etapa 3 está encendido por entorno")
class TestApagadoPorDefecto(unittest.TestCase):
    def test_interruptores_apagados(self):
        self.assertFalse(ctx.USAR_GLOSARIO or ctx.USAR_ESQUEMA_POR_PREGUNTA or ctx.USAR_FEWSHOT_DINAMICO or ctx.USAR_PLAN)
        self.assertEqual(ctx.K_AUTOCONSISTENCIA, 1)
        self.assertFalse(sc.USAR_DESC_COLUMNAS or sc.USAR_VISTAS_NEGOCIO)

    def test_sin_cambios_en_el_contexto(self):
        self.assertIsNone(ctx.contexto_usuario("¿Qué porcentaje de pedidos llegó tarde?"))
        self.assertFalse(ctx.depende_de_la_pregunta())
        self.assertEqual(sc.build_schema_context(), sc.get_schema_context())
        for v in sc.VISTAS_NEGOCIO_DESCRIPCION:
            self.assertNotIn(v, sc.get_schema_context())
            self.assertIn(v, sc.get_known_names())  # el validador las conoce aunque no estén en el prompt


class TestE1Glosario(unittest.TestCase):
    def test_solo_entradas_disparadas(self):
        terminos = {e["termino"] for e in ctx.entradas_glosario("¿Qué tasa de pedidos llegó con retraso?")}
        self.assertIn("porcentaje", terminos)
        self.assertIn("retraso", terminos)
        self.assertNotIn("ticket promedio", terminos)
        self.assertIsNone(ctx.texto_glosario("zzz"))

    def test_fragmentos_sql_lejos_del_oraculo(self):
        for e in ctx.glosario():
            for q in preguntas_oraculo():
                self.assertLess(jaccard(tokens_sql(e["sql"]), tokens_sql(q["sql_referencia"])), 0.5, (e["termino"], q["id"]))


class TestE2SeleccionDeEsquema(unittest.TestCase):
    def test_tablas_puente(self):
        tablas, vistas = ctx.seleccion_esquema("¿Qué categoría tiene más reseñas de 1 estrella?")
        self.assertTrue({"products", "product_category_translation", "order_reviews", "order_items", "orders"} <= tablas)
        self.assertNotIn("geolocation", tablas)
        self.assertIn("vw_pedidos_validos", vistas)

    def test_esquema_reducido_es_mas_corto_y_conserva_las_tablas(self):
        tablas, vistas = ctx.seleccion_esquema("¿Cuántos vendedores hay?")
        reducido = sc.build_schema_context(tablas=tablas, vistas_visibles=vistas)
        self.assertLess(len(reducido), len(sc.get_schema_context()))
        self.assertIn("sellers(", reducido)
        self.assertNotIn("geolocation(", reducido)


class TestE3E4(unittest.TestCase):
    def test_columnas_descritas_existen(self):
        esquema = sc.get_esquema_real()
        for (t, c) in sc.DESCRIPCIONES_COLUMNAS:
            self.assertIn(c, esquema[t], f"{t}.{c}")

    def test_vistas_de_negocio_existen(self):
        esquema = sc.get_esquema_real()
        for v in sc.VISTAS_NEGOCIO_DESCRIPCION:
            self.assertIn(v, esquema)


class TestE5FewShotDinamico(unittest.TestCase):
    def test_banco_y_seleccion(self):
        self.assertGreaterEqual(len(ctx.banco()), 30)
        elegidos = ctx.ejemplos_parecidos("¿Cuántas reseñas hay de cada puntuación?")
        self.assertEqual(len(elegidos), 3)
        self.assertIn("review_score", elegidos[0][1])


class TestE6Plan(unittest.TestCase):
    def test_la_regla_existe_una_vez(self):
        self.assertEqual(SQL_SYSTEM_PROMPT_TEMPLATE.count(ctx.REGLA_SOLO_SQL), 1)


class _Guion:
    model, host, temperature, num_ctx = "guion", "-", 0.0, 0

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)

    def generate(self, prompt, system=None, **kw):
        return self.respuestas.pop(0)


class TestE7Autoconsistencia(unittest.TestCase):
    def test_elige_el_resultado_mayoritario(self):
        a = "```sql\nSELECT COUNT(*) FROM sellers\n```"
        b = "```sql\nSELECT COUNT(*) FROM customers\n```"
        malo = "```sql\nSELECT columna_que_no_existe FROM sellers\n```"
        sql, info = _elegir_por_autoconsistencia(_Guion([b, a, malo, a, a]), "p", sc.get_schema_context(), None, 5,
                                                 sc.get_known_names(), sc.get_esquema_real())
        self.assertIn("sellers", sql)
        self.assertEqual((info["ejecutables_con_filas"], info["resultados_distintos"], info["votos_ganador"]), (4, 2, 3))

    def test_si_nada_corre_devuelve_el_primero(self):
        malo = "```sql\nSELECT columna_que_no_existe FROM sellers\n```"
        sql, info = _elegir_por_autoconsistencia(_Guion([malo, malo, malo]), "p", sc.get_schema_context(), None, 3,
                                                 sc.get_known_names(), sc.get_esquema_real())
        self.assertIn("columna_que_no_existe", sql)
        self.assertEqual(info["votos_ganador"], 0)


if __name__ == "__main__":
    unittest.main()
