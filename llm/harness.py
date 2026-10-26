"""
Harness (mejoras del profesor, fase D; D-45): RAG + todo el arnés que ya existe, expuesto como un modo.

  modo=harness = ejemplos recuperados por RAG (llm/rag.py)
               + validadores de sql_guard y ejecución de solo lectura (ya en el pipeline)
               + reintento con el error real y reparación con el esquema real (D-40, ya en el pipeline)
               + chequeo de "texto confiable" con umbrales (D-40, ya en el pipeline)
               + hasta N_INTENTOS_HARNESS intentos con un VERIFICADOR SIN ORÁCULO entre intentos:
                 chequeos de sensatez del resultado (llm/juez.py) y revisión del juez-LLM de sensatez.

El verificador no conoce la respuesta correcta: sirve igual en el chat. El juez con oráculo
(llm/juez.resolver_con_juez) sigue siendo solo de evaluación.

`ClienteMedido` envuelve al cliente de Ollama y registra cada llamada (rol, tokens, tiempo), para el
registro por intento y la comparación de modos.
"""
from __future__ import annotations

import time

from llm.ollama_client import OllamaClient, OllamaError

N_INTENTOS_HARNESS = 5


def _aviso_sensatez_grave(columnas: list[str], filas: list[list]) -> list[str]:
    """Solo los chequeos que casi siempre indican un error (los negativos pueden ser legítimos, p. ej. días
    de adelanto)."""
    from llm.juez import chequeos_sensatez

    return [a for a in chequeos_sensatez(columnas, [list(f) for f in filas])
            if "mayores que 100" in a or "NULL en todas" in a or "división entera" in a]


def verificador_sin_oraculo(client: OllamaClient, pregunta: str, registro: list | None = None):
    """Verificador para `answer_question(verificador=...)`: (aceptado, pista). Rechaza si el resultado
    falla un chequeo de sensatez grave o si el juez-LLM dice que el SQL no tiene sentido para la pregunta."""
    from llm.juez import JuezLLM

    juez = JuezLLM(client)

    def verificar(sql: str, columnas: list[str], filas: list) -> tuple[bool, str | None]:
        avisos = _aviso_sensatez_grave(columnas, filas)
        if avisos:
            pista = "El resultado no es plausible: " + " ".join(avisos) + " Revisa el cálculo."
            if registro is not None:
                registro.append({"verificador": "sensatez", "aceptado": False, "pista": pista})
            return False, pista
        opinion = juez.evaluar_sensatez(pregunta, sql)
        aceptado = opinion.valor is not False  # None (sin JSON interpretable) no bloquea
        pista = None if aceptado else f"Un revisor indica que la consulta no responde la pregunta: {opinion.motivo}"
        if registro is not None:
            registro.append({"verificador": "juez_sensatez", "aceptado": aceptado, "motivo": opinion.motivo})
        return aceptado, pista

    return verificar


class ClienteMedido:
    """Mismo `generate` que OllamaClient, pero por debajo usa generate_detallado y anota cada llamada."""

    def __init__(self, cliente: OllamaClient, seed: int | None = None):
        self._cliente = cliente
        self.seed = seed
        self.llamadas: list[dict] = []

    def __getattr__(self, nombre):
        return getattr(self._cliente, nombre)

    @staticmethod
    def _rol(system: str | None) -> str:
        s = system or ""
        if s.startswith("Eres un generador de consultas SQL"):
            return "sql"
        if s.startswith("Eres un analista de datos"):
            return "sintesis"
        if s.startswith("Eres un revisor experto"):
            return "juez"
        return "otro"

    def generate(self, prompt, system=None, num_predict: int = 400, temperature=None, options=None):
        t0 = time.perf_counter()
        try:
            r = self._cliente.generate_detallado(prompt, system=system, num_predict=num_predict,
                                                 temperature=temperature, seed=self.seed)
        except OllamaError:
            self.llamadas.append({"rol": self._rol(system), "error": True, "segundos": time.perf_counter() - t0})
            raise
        self.llamadas.append({
            "rol": self._rol(system), "segundos": round(time.perf_counter() - t0, 3),
            "prompt_eval_count": r.get("prompt_eval_count"), "eval_count": r.get("eval_count"),
            "caracteres_prompt": len(system or "") + len(prompt),
        })
        return r["response"]

    def resumen(self) -> dict:
        sql = [ll for ll in self.llamadas if ll["rol"] == "sql" and not ll.get("error")]
        return {
            "llamadas": len(self.llamadas),
            "llamadas_sql": len(sql),
            "tokens_prompt_sql": sum(ll["prompt_eval_count"] or 0 for ll in sql),
            "tokens_prompt_total": sum(ll.get("prompt_eval_count") or 0 for ll in self.llamadas),
            "tokens_generados_total": sum(ll.get("eval_count") or 0 for ll in self.llamadas),
            "caracteres_prompt_sql_max": max((ll["caracteres_prompt"] for ll in sql), default=0),
            "segundos_llm": round(sum(ll["segundos"] for ll in self.llamadas), 2),
        }


def registro_por_intento(resultado, medido: ClienteMedido | None = None) -> list[dict]:
    """Un dict por intento: SQL, tipo y error, ejemplos usados y, si hay ClienteMedido, tokens y tiempo de la
    llamada de generación de SQL de ese intento (en orden)."""
    sql_calls = [ll for ll in (medido.llamadas if medido else []) if ll["rol"] == "sql"]
    salida = []
    for k, d in enumerate(resultado.intentos_detalle):
        ll = sql_calls[k] if k < len(sql_calls) else {}
        salida.append({
            "intento": d.get("intento"), "sql": d.get("sql"), "tipo": d.get("tipo"), "error": d.get("detalle"),
            "pista_siguiente": d.get("pista_siguiente"), "ejemplos_usados": [e["id"] for e in resultado.ejemplos_usados],
            "tokens_prompt": ll.get("prompt_eval_count"), "segundos_generacion": ll.get("segundos"),
        })
    return salida
