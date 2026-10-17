"""
Flags del cierre del juez (D-40): TEXT2SQL_REPARAR_ESQUEMA y TEXT2SQL_TEXTO_UMBRALES.
Encendidos por defecto desde D-40 (cumplieron D-23). Apagados, el chat se comporta como antes;
encendidos, el reintento lleva las columnas reales y la ruta por tablas base, y la síntesis
acepta los umbrales de la pregunta.
"""
from __future__ import annotations

import unittest
from unittest import mock

from llm import text_to_sql as t
from llm.schema_context import get_known_names


class _ClienteGuion:
    """Devuelve primero un SQL con una columna inexistente y luego uno válido; guarda los prompts."""
    model, host, temperature, num_ctx = "falso", "-", 0.0, 8192

    def __init__(self):
        self.prompts = []
        self.respuestas = iter([
            "```sql\nSELECT p.payment_installments FROM products p\n```",
            "```sql\nSELECT COUNT(*) AS n FROM order_payments\n```",
        ])

    def generate(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        return next(self.respuestas)


def _segundo_prompt(reparar: bool) -> str:
    cliente = _ClienteGuion()
    with mock.patch.object(t, "USAR_REPARAR_ESQUEMA", reparar), mock.patch.object(t.contexto_e3, "K_AUTOCONSISTENCIA", 1):
        r = t._generar_y_ejecutar_llm(cliente, "¿Cuántos pagos a plazos hay?", "(esquema)", get_known_names(), 2)
    assert r.filas, r.error_detalle
    return cliente.prompts[1]


class TestReparacionEnElChat(unittest.TestCase):
    def test_apagado_el_reintento_solo_lleva_el_error(self):
        prompt = _segundo_prompt(False)
        self.assertIn("no tiene la columna 'payment_installments'", prompt)
        self.assertNotIn("Reparación con el esquema real", prompt)

    def test_encendido_lleva_columnas_reales_y_ruta(self):
        prompt = _segundo_prompt(True)
        self.assertIn("no tiene la columna 'payment_installments'", prompt)
        self.assertIn("columnas reales de products", prompt)
        self.assertIn("products → order_items (por product_id) → order_payments (por order_id)", prompt)

    def test_encendidos_por_defecto_tras_d23(self):
        # D-40: cumplieron D-23; se apagan con TEXT2SQL_REPARAR_ESQUEMA=0 / TEXT2SQL_TEXTO_UMBRALES=0.
        import os
        if "TEXT2SQL_REPARAR_ESQUEMA" not in os.environ:
            self.assertTrue(t.USAR_REPARAR_ESQUEMA)
        if "TEXT2SQL_TEXTO_UMBRALES" not in os.environ:
            self.assertTrue(t.USAR_TEXTO_UMBRALES)


class TestTextoUmbrales(unittest.TestCase):
    PREGUNTA = "Entre las categorías con ingresos de al menos R$ 5,000, ¿cuál tiene más flete?"
    TEXTO = "Con ingresos de al menos R$ 5,000, la primera es christmas_supplies con 36.66%."
    FILAS = [("christmas_supplies", 36.66)]

    def test_apagado_no_cambia_el_chequeo(self):
        with mock.patch.object(t, "USAR_TEXTO_UMBRALES", False):
            self.assertIsNone(t._numeros_extra_sintesis(self.PREGUNTA))
            self.assertFalse(t._respuesta_respaldada_por_datos(self.TEXTO, self.FILAS, t._numeros_extra_sintesis(self.PREGUNTA)))

    def test_encendido_acepta_el_umbral_pero_no_cifras_inventadas(self):
        with mock.patch.object(t, "USAR_TEXTO_UMBRALES", True):
            extra = t._numeros_extra_sintesis(self.PREGUNTA)
            self.assertTrue(t._respuesta_respaldada_por_datos(self.TEXTO, self.FILAS, extra))
            self.assertFalse(t._respuesta_respaldada_por_datos(self.TEXTO + " Suman 12,345.", self.FILAS, extra))


if __name__ == "__main__":
    unittest.main()
