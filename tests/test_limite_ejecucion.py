"""
El SQL generado por el modelo se corta si supera el límite de ejecución
(llm/text_to_sql.py: execute_readonly). Motivo: en la primera corrida de
baseline_01 una consulta de q4 quedó corriendo >10 min (docs/FASE_03.md).

Uso: python -m unittest tests.test_limite_ejecucion -v
"""
import sqlite3
import time
import unittest

from llm.text_to_sql import execute_readonly

CARTESIANO = "SELECT COUNT(*) FROM order_items a, order_items b"


class TestLimiteEjecucion(unittest.TestCase):
    def test_producto_cartesiano_se_corta(self):
        t0 = time.perf_counter()
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            execute_readonly(CARTESIANO, limite_s=2)
        transcurrido = time.perf_counter() - t0
        self.assertIn("superó el límite de 2 s", str(ctx.exception))
        self.assertLess(transcurrido, 5, f"tardó {transcurrido:.1f} s en cortar")
        print(f"\n  cartesiano cortado en {transcurrido:.2f} s: {ctx.exception}")

    def test_consulta_normal_no_se_afecta(self):
        columnas, filas = execute_readonly("SELECT COUNT(*) FROM orders", limite_s=2)
        self.assertEqual(filas, [(99441,)])


if __name__ == "__main__":
    unittest.main()
