"""
Fase 3: pruebas del árbitro determinista (eval/comparador.py).

Uso: python -m unittest tests.test_comparador -v
"""
import json
import sqlite3
import unittest
from pathlib import Path

from eval.comparador import comparar, valor_coincide

RAIZ = Path(__file__).resolve().parent.parent
GT = {q["id"]: q for q in json.loads((RAIZ / "eval" / "ground_truth_olist_v1.json").read_text(encoding="utf-8"))["preguntas"]}


def _referencia(qid):
    conn = sqlite3.connect(f"file:{RAIZ / 'db' / 'olist.db'}?mode=ro", uri=True)
    try:
        return conn.execute(GT[qid]["sql_referencia"]).fetchall()
    finally:
        conn.close()


class TestQ2ValorViejoRechazado(unittest.TestCase):
    """En baseline_00 la tolerancia de q2 era 2 % (±≈25,000 R$) y aceptaba
    tanto 1,258,681.34 (definición vieja) como 1,255,695.13 (vigente)."""

    def setUp(self):
        self.ref = _referencia("q2_categoria_mas_ingresos")
        self.tipos = GT["q2_categoria_mas_ingresos"]["tipos_columnas"]

    def test_referencia_es_la_vigente(self):
        self.assertEqual(self.ref, [("health_beauty", 1255695.13)])

    def test_valor_viejo_se_rechaza(self):
        v = comparar([("health_beauty", 1258681.34)], self.ref, self.tipos)
        self.assertFalse(v.correcto, v.motivo)

    def test_valor_vigente_se_acepta(self):
        self.assertTrue(comparar([("health_beauty", 1255695.13)], self.ref, self.tipos).correcto)

    def test_sin_redondear_se_acepta(self):
        self.assertTrue(comparar([("health_beauty", 1255695.1299999), ], self.ref, self.tipos).correcto)

    def test_columnas_en_otro_orden_y_extra(self):
        self.assertTrue(comparar([(1255695.13, 12345, "HEALTH_BEAUTY")], self.ref, self.tipos).correcto)

    def test_categoria_equivocada(self):
        self.assertFalse(comparar([("watches_gifts", 1255695.13)], self.ref, self.tipos).correcto)

    def test_mas_filas_que_la_referencia(self):
        v = comparar([("health_beauty", 1255695.13), ("watches_gifts", 1198185.21)], self.ref, self.tipos)
        self.assertFalse(v.correcto)
        self.assertIn("filas", v.motivo)


class TestValoresViejosDeQ6yQ10(unittest.TestCase):
    def test_q6_viejo_y_baseline00(self):
        ref, tipos = _referencia("q6_metodo_pago_mayor_venta_promedio"), GT["q6_metodo_pago_mayor_venta_promedio"]["tipos_columnas"]
        self.assertFalse(comparar([("credit_card", 163.94)], ref, tipos).correcto)  # definición vieja
        self.assertFalse(comparar([("credit_card", 162.70393992490614)], ref, tipos).correcto)  # aceptado en baseline_00
        self.assertTrue(comparar([("credit_card", 163.32)], ref, tipos).correcto)

    def test_q10_viejo(self):
        ref, tipos = _referencia("q10_ticket_promedio_pedido"), GT["q10_ticket_promedio_pedido"]["tipos_columnas"]
        self.assertFalse(comparar([(160.58,)], ref, tipos).correcto)
        self.assertTrue(comparar([(160.24,)], ref, tipos).correcto)


class TestTolerancias(unittest.TestCase):
    def test_conteo_exacto(self):
        self.assertTrue(valor_coincide(99441, 99441, "conteo"))
        self.assertTrue(valor_coincide(99441.0, 99441, "conteo"))
        self.assertFalse(valor_coincide(99440, 99441, "conteo"))

    def test_dinero(self):
        self.assertTrue(valor_coincide(160.245, 160.24, "dinero"))      # medio centavo
        self.assertTrue(valor_coincide(1255000.00, 1255695.13, "dinero"))  # 0.055 % < 0.1 %
        self.assertTrue(valor_coincide(160.40, 160.24, "dinero"))       # 0.0998 % <= 0.1 %
        self.assertFalse(valor_coincide(160.50, 160.24, "dinero"))      # 0.162 % > 0.1 %

    def test_porcentaje(self):
        self.assertTrue(valor_coincide(3.0412, 3.04, "porcentaje"))
        self.assertTrue(valor_coincide(0.030412, 3.04, "porcentaje"))   # escala fracción
        self.assertFalse(valor_coincide(3.10, 3.04, "porcentaje"))
        self.assertFalse(valor_coincide(100.0, 3.04, "porcentaje"))     # caso q3 de baseline_00

    def test_decimal(self):
        self.assertTrue(valor_coincide(12.5588, 12.56, "decimal"))
        self.assertFalse(valor_coincide(-11.18, 12.56, "decimal"))      # caso q8 de baseline_00
        self.assertFalse(valor_coincide(12.6, 12.56, "decimal"))

    def test_texto(self):
        self.assertTrue(valor_coincide(" SP ", "SP", "texto"))
        self.assertFalse(valor_coincide("São Paulo", "SP", "texto"))


class TestEstructura(unittest.TestCase):
    def test_q5_columnas_iguales_en_ambas_es_falso(self):
        # baseline_00: el modelo devolvió ~2.57 en ambas columnas
        ref = _referencia("q5_retraso_baja_calificacion")
        tipos = GT["q5_retraso_baja_calificacion"]["tipos_columnas"]
        self.assertFalse(comparar([(2.566525260316236, 2.566525260316236)], ref, tipos).correcto)

    def test_q4_orden_importa(self):
        ref = _referencia("q4_categorias_mas_compra_unica")
        tipos = GT["q4_categorias_mas_compra_unica"]["tipos_columnas"]
        correcto = [(f[0], f[3]) for f in ref]
        self.assertTrue(comparar(correcto, ref, tipos, orden_importa=True).correcto)
        self.assertFalse(comparar(list(reversed(correcto)), ref, tipos, orden_importa=True).correcto)

    def test_sin_orden_compara_como_conjunto(self):
        ref = [("a", 1), ("b", 2)]
        self.assertTrue(comparar([("b", 2), ("a", 1)], ref, ["texto", "conteo"]).correcto)

    def test_sin_filas_del_modelo(self):
        v = comparar([], _referencia("q1_pedidos_totales"), ["conteo"])
        self.assertFalse(v.correcto)


class TestOraculoCompleto(unittest.TestCase):
    def test_cada_referencia_se_acepta_a_si_misma(self):
        for qid, q in GT.items():
            ref = _referencia(qid)
            v = comparar(ref, ref, q["tipos_columnas"], q.get("orden_importa", False))
            self.assertTrue(v.correcto, f"{qid}: {v.motivo}")

    def test_oraculo_v2_cada_referencia_se_acepta_a_si_misma_y_coincide_con_lo_guardado(self):
        v2 = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
        self.assertEqual(len(v2), 10)
        conn = sqlite3.connect(f"file:{RAIZ / 'db' / 'olist.db'}?mode=ro", uri=True)
        try:
            for q in v2:
                ref = conn.execute(q["sql_referencia"]).fetchall()
                self.assertEqual([list(f) for f in ref], q["resultado_esperado"], q["id"])
                v = comparar(ref, ref, q["tipos_columnas"], q["orden_importa"])
                self.assertTrue(v.correcto, f"{q['id']}: {v.motivo}")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
