"""
Etapa 3, Paso 1: auditoría del contexto EXACTO que recibe el generador de SQL.

Captura el system prompt y el prompt de usuario de `generar_sql` (sin cambiar nada
del pipeline) para 3 preguntas genéricas, lo parte por secciones y mide caracteres
y tokens. Los tokens los cuenta el tokenizador real del modelo vía Ollama
(`/api/generate` con raw=true y num_predict=1 -> prompt_eval_count). Para que la
caché de prefijos de Ollama no descuente tokens, cada medición empieza con un
prefijo único que luego se resta.

Uso: python -m eval.auditar_contexto            (escribe eval/baselines/etapa3/auditoria_contexto.json)
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import requests

from llm import schema_context as sc
from llm.ollama_client import OllamaClient
from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE, generar_sql

RAIZ = Path(__file__).resolve().parent.parent
# Genéricas, escritas para la auditoría (no salen del oráculo).
PREGUNTAS = [
    "¿Cuántos vendedores hay en el estado de PR?",
    "¿Qué porcentaje de los pagos se hizo con voucher?",
    "¿Cuál es el tiempo promedio, en días, entre la aprobación del pedido y la entrega al cliente?",
]


class _Captura:
    model, host, temperature, num_ctx = "captura", "-", 0.0, 0

    def __init__(self):
        self.llamadas = []

    def generate(self, prompt, system=None, **kw):
        self.llamadas.append({"system": system or "", "prompt": prompt, "kw": kw})
        return "```sql\nSELECT 1\n```"


def _tokens(texto: str, client: OllamaClient) -> int:
    def pec(t: str) -> int:
        r = requests.post(f"{client.host}/api/generate", json={
            "model": client.model, "prompt": t, "raw": True, "stream": False,
            "options": {"num_predict": 1, "num_ctx": client.num_ctx, "temperature": 0}}, timeout=300)
        r.raise_for_status()
        return r.json()["prompt_eval_count"]
    marca = f"[{uuid.uuid4().hex[:8]}]\n"
    return pec(marca + texto) - pec(marca)


def secciones_del_system(system: str) -> dict[str, str]:
    """Parte el system prompt en las secciones que arma build_schema_context."""
    esquema = sc.get_schema_context()
    i = system.index(esquema)
    partes = {"instrucciones (antes del esquema)": system[:i], "reglas estrictas (después del esquema)": system[i + len(esquema):]}
    marcas = [
        ("tablas (columnas y tipos)", "Tablas disponibles (SQLite):"),
        ("vistas", "Vistas analíticas disponibles"),
        ("columnas de unión", None),
        ("valores categóricos", None),
        ("notas / reglas de negocio", "Notas importantes:"),
        ("ejemplos few-shot", "Ejemplos de pregunta -> SQL correcto:"),
    ]
    union = sc._columnas_de_union_texto()
    valores = sc._valores_categoricos_texto() or ""
    pos = {
        "tablas (columnas y tipos)": esquema.index("Tablas disponibles (SQLite):"),
        "vistas": esquema.index("Vistas analíticas disponibles"),
        "columnas de unión": esquema.index(union),
        "valores categóricos": esquema.index(valores) if valores else None,
        "notas / reglas de negocio": esquema.index("Notas importantes:"),
        "ejemplos few-shot": esquema.index("Ejemplos de pregunta -> SQL correcto:"),
    }
    orden = sorted((p, n) for n, p in pos.items() if p is not None)
    for k, (p, n) in enumerate(orden):
        fin = orden[k + 1][0] if k + 1 < len(orden) else len(esquema)
        partes[n] = esquema[p:fin]
    assert sum(len(v) for v in partes.values()) == len(system), "las secciones no cubren el system prompt"
    return partes


def main():
    client = OllamaClient()
    cap = _Captura()
    for p in PREGUNTAS:
        generar_sql(cap, p, sc.get_schema_context())
    systems = {c["system"] for c in cap.llamadas}
    system = cap.llamadas[0]["system"]
    partes = secciones_del_system(system)
    filas = []
    for nombre, texto in partes.items():
        filas.append({"seccion": nombre, "caracteres": len(texto), "tokens": _tokens(texto, client)})
    total_tokens = _tokens(system, client)
    salida = {
        "modelo": client.model, "temperatura_pipeline": client.temperature, "num_ctx": client.num_ctx,
        "system_identico_en_las_3_preguntas": len(systems) == 1,
        "system_caracteres": len(system), "system_tokens": total_tokens,
        "secciones": filas,
        "prompts_usuario": [{"pregunta": c["prompt"], "caracteres": len(c["prompt"]), "tokens": _tokens(c["prompt"], client),
                             "num_predict": c["kw"].get("num_predict")} for c in cap.llamadas],
        "system_prompt": system,
    }
    destino = RAIZ / "eval" / "baselines" / "etapa3" / "auditoria_contexto.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in salida.items() if k != "system_prompt"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
