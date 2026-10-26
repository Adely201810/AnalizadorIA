"""
Banco de necesidades negativas (D-41): esquema del JSON, SQL ejecutable en solo lectura con el
resultado guardado, respuesta en lenguaje natural respaldada por ese resultado y ANTI-CONTAMINACIÓN
frente a todas las preguntas de evaluación (oráculo v4 completo y casos del juez).

Umbrales (fijados antes de medir, D-41): Jaccard de texto < 0.35 (pregunta y variantes), Jaccard de
SQL < 0.70, SQL normalizado distinto, y el resultado de la negativa no acierta ninguna pregunta de
evaluación (copiar su SQL no da la respuesta correcta).
"""
from __future__ import annotations

import unittest

from llm.banco_ejemplos import cargar_banco, familias
from llm.banco_ejemplos import construir as c
from llm.banco_ejemplos.definiciones import NECESIDADES

CAMPOS = {"id", "familia", "pregunta", "variantes", "en_que_se_diferencia", "sql", "resumen_resultado",
          "respuesta_nl", "trampas", "similitud_maxima_evaluacion"}
FAMILIAS_REALES = {"2 · Retraso vs reseñas", "4 · Vendedores problemáticos", "5 · Flete", "6 · Pagos",
                   "8 · Insatisfacción"}


class TestBancoNegativas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.banco = cargar_banco()
        cls.evaluacion = c.preguntas_evaluacion()
        cls.ejecutado = {e["id"]: c._ejecutar(e["sql"]) for e in cls.banco}  # una ejecución por SQL

    def test_tamano_y_familias(self):
        self.assertGreaterEqual(len(self.banco), 30)
        self.assertLessEqual(len(self.banco), 40)
        self.assertEqual(set(familias()), FAMILIAS_REALES)
        for fam in FAMILIAS_REALES:
            self.assertGreaterEqual(sum(e["familia"] == fam for e in self.banco), 6, fam)

    def test_esquema_del_json(self):
        ids = [e["id"] for e in self.banco]
        self.assertEqual(len(ids), len(set(ids)))
        for e in self.banco:
            self.assertEqual(set(e), CAMPOS, e["id"])
            self.assertTrue(e["variantes"] and e["trampas"] and e["respuesta_nl"], e["id"])
            self.assertEqual(set(e["resumen_resultado"]), {"columnas", "filas", "total_filas"})

    def test_el_json_coincide_con_las_definiciones(self):
        self.assertEqual([e["id"] for e in self.banco], [d["id"] for d in NECESIDADES])
        for e, d in zip(self.banco, NECESIDADES):
            self.assertEqual(e["sql"], d["sql"], e["id"])
            self.assertEqual(e["pregunta"], d["pregunta"], e["id"])

    def test_sql_ejecuta_y_reproduce_el_resultado_guardado(self):
        for e in self.banco:
            columnas, filas = self.ejecutado[e["id"]]
            self.assertEqual(c._problemas_resultado(columnas, filas), [], e["id"])
            self.assertEqual(columnas, e["resumen_resultado"]["columnas"], e["id"])
            self.assertEqual(filas[:5], e["resumen_resultado"]["filas"], e["id"])

    def test_respuesta_respaldada_por_el_resultado(self):
        from llm.juez import _numeros_en
        from llm.text_to_sql import _respuesta_respaldada_por_datos

        for e in self.banco:
            filas = [tuple(f) for f in e["resumen_resultado"]["filas"]]
            self.assertTrue(_respuesta_respaldada_por_datos(e["respuesta_nl"], filas, _numeros_en(e["pregunta"])), e["id"])

    def test_anticontaminacion(self):
        for e in self.banco:
            _, filas = self.ejecutado[e["id"]]
            cont = c.contaminacion(e, filas, self.evaluacion)
            self.assertEqual(cont["violaciones"], [], e["id"])

    def test_la_evaluacion_cubre_los_tres_conjuntos(self):
        origenes = {q["origen"] for q in self.evaluacion}
        self.assertEqual(origenes, {"desarrollo", "prueba_2", "casos_juez"})
        self.assertEqual(len(self.evaluacion), 56)


if __name__ == "__main__":
    unittest.main()
