"""
Etapa 3, Paso 3: experimentos de CONTEXTO, cada uno detrás de un interruptor de
entorno APAGADO por defecto (con todos apagados, el prompt es idéntico al anterior).

  E1 TEXT2SQL_GLOSARIO=1              glosario de negocio: solo las entradas cuyo término aparece en la pregunta
  E2 TEXT2SQL_ESQUEMA_POR_PREGUNTA=1  solo las tablas/vistas relevantes para la pregunta (+ claves de unión)
  E3 TEXT2SQL_DESC_COLUMNAS=1         una línea por columna ambigua            (llm/schema_context.py)
  E4 TEXT2SQL_VISTAS_NEGOCIO=1        vistas de negocio genéricas en el prompt (llm/schema_context.py)
  E5 TEXT2SQL_FEWSHOT_DINAMICO=1      3 ejemplos del banco más parecidos (TF-IDF) en lugar de los 10 fijos
  E6 TEXT2SQL_PLAN=1                  el modelo escribe un plan breve antes del SQL
  E7 TEXT2SQL_AUTOCONSISTENCIA=k      genera k SQL, los ejecuta y elige el resultado más frecuente

Nada de lo que se inyecta sale del oráculo: el glosario y el banco de ejemplos son
genéricos y lo comprueban tests/test_heldout.py y tests/test_fewshot_disjunto.py.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from llm import schema_context as sc

DIR = Path(__file__).resolve().parent
USAR_GLOSARIO = os.environ.get("TEXT2SQL_GLOSARIO", "0") == "1"
USAR_ESQUEMA_POR_PREGUNTA = os.environ.get("TEXT2SQL_ESQUEMA_POR_PREGUNTA", "0") == "1"
USAR_FEWSHOT_DINAMICO = os.environ.get("TEXT2SQL_FEWSHOT_DINAMICO", "0") == "1"
N_FEWSHOT_DINAMICO = 3
USAR_PLAN = os.environ.get("TEXT2SQL_PLAN", "0") == "1"
K_AUTOCONSISTENCIA = max(1, int(os.environ.get("TEXT2SQL_AUTOCONSISTENCIA", "1")))

REGLA_SOLO_SQL = "- Responde ÚNICAMENTE con la consulta SQL dentro de un bloque ```sql ... ```. Nada de explicaciones."
REGLA_PLAN = (
    "- Primero escribe un plan breve, de 2 a 4 líneas que empiecen con 'Plan:': qué tablas o vistas usarás, qué "
    "filtros, cuál es el denominador si hay un porcentaje, y cómo agruparás y ordenarás. Después escribe la consulta "
    "SQL dentro de un bloque ```sql ... ```. Nada más."
)
NUM_PREDICT_CON_PLAN = 700


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos (para comparar disparadores y palabras clave)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


# --------------------------------------------------------------------- E1 glosario
@lru_cache(maxsize=1)
def glosario() -> list[dict]:
    return json.loads((DIR / "glosario_negocio.json").read_text(encoding="utf-8"))["entradas"]


def entradas_glosario(pregunta: str) -> list[dict]:
    q = normalizar(pregunta)
    return [e for e in glosario() if any(normalizar(d) in q for d in e["disparadores"])]


def texto_glosario(pregunta: str) -> str | None:
    entradas = entradas_glosario(pregunta)
    if not entradas:
        return None
    lineas = ["Definiciones de negocio que aplican a esta pregunta:"]
    for e in entradas:
        lineas.append(f"- {e['termino']}: {e['definicion']}\n  SQL: {e['sql']}")
    return "\n".join(lineas)


# --------------------------------------------------------------------- E2 esquema por pregunta
# Palabras clave por tabla, escritas desde el significado de cada tabla (no desde preguntas).
CLAVES_TABLAS = {
    "customers": ["cliente", "comprador", "persona", "ciudad", "estado", "codigo postal"],
    "sellers": ["vendedor", "tienda", "seller"],
    "orders": ["pedido", "compra", "orden", "estatus", "status", "cancel", "entreg", "fecha", "mes", "ano", "anio",
               "retras", "aprob", "transportista", "dias"],
    "order_items": ["articulo", "unidad", "item", "precio", "price", "flete", "ingreso", "venta", "vendid", "vendio",
                    "producto"],
    "order_payments": ["pago", "pagad", "cobrad", "tarjeta", "boleto", "voucher", "cuota", "debito", "credito", "ticket"],
    "order_reviews": ["resena", "calificacion", "estrella", "comentario", "review", "puntuacion", "encuesta",
                      "satisfaccion"],
    "products": ["producto", "categoria", "peso", "gramo", "kilo", "foto", "imagen", "medida", "largo", "alto",
                 "ancho", "volumen", "descripcion", "catalogo"],
    "product_category_translation": ["categoria", "ingles", "traduc"],
    "geolocation": ["geolocaliz", "latitud", "longitud", "coordenada"],
}
# Tablas que se necesitan para unir las seleccionadas (orders es el centro del esquema).
SIEMPRE = {"orders"}
CLAVES_VISTAS = {
    "vw_pedidos_validos": ["valido", "cancel", "no disponible", "anulad"],
    "vw_ventas_pedido": ["articulo", "linea de pedido", "categoria", "venta"],
    "vw_clientes_recurrentes": ["recurrente", "recompra", "volvio", "una sola vez", "gasto total"],
    "vw_entregas_retrasos": ["retras", "a tiempo", "tard"],
    "vw_ingresos_por_categoria": ["ingreso", "categoria"],
    "vw_ingresos_por_vendedor": ["ingreso", "vendedor"],
    "vw_retraso_por_rango": ["rango"],
    "vw_pedidos_entregados": ["entreg", "retras", "a tiempo", "dias"],
    "vw_totales_pedido": ["pedido", "ticket", "pagad", "cobrad", "gasto", "total"],
    "vw_articulos_vendidos": ["articulo", "unidad", "vendid", "categoria", "vendedor", "ingreso"],
}
# Las vistas con "Y" entre palabras clave (necesitan las dos ideas) para no colarse siempre.
VISTAS_CONJUNTIVAS = {"vw_ingresos_por_categoria", "vw_ingresos_por_vendedor"}


def seleccion_esquema(pregunta: str) -> tuple[set[str], set[str]]:
    """(tablas, vistas) relevantes para la pregunta por coincidencia léxica, con las tablas
    puente que hacen falta para unirlas."""
    q = normalizar(pregunta)
    tablas = {t for t, claves in CLAVES_TABLAS.items() if any(c in q for c in claves)} | SIEMPRE
    if "product_category_translation" in tablas:
        tablas.add("products")
    if tablas & {"products", "sellers"}:
        tablas.add("order_items")  # producto o vendedor de un pedido: se llega por order_items
    if "customers" in tablas or tablas & {"order_items", "order_payments", "order_reviews"}:
        tablas.add("orders")
    vistas = set()
    for v, claves in CLAVES_VISTAS.items():
        hits = [c for c in claves if c in q]
        if (v in VISTAS_CONJUNTIVAS and len(hits) >= 2) or (v not in VISTAS_CONJUNTIVAS and hits):
            vistas.add(v)
    vistas.add("vw_pedidos_validos")  # la vista base de la configuración final: siempre visible
    return tablas, vistas


# --------------------------------------------------------------------- E5 few-shot dinámico
_PALABRA = re.compile(r"[a-z0-9_]+")
_VACIAS = {"de", "la", "el", "los", "las", "en", "y", "o", "que", "un", "una", "por", "con", "del", "al", "se", "a",
           "es", "su", "sus", "lo", "para", "cual", "cuales", "cuanto", "cuantos", "cuanta", "cuantas", "como", "mas"}


def _tokens(texto: str) -> list[str]:
    return [w for w in _PALABRA.findall(normalizar(texto)) if w not in _VACIAS]


@lru_cache(maxsize=1)
def banco() -> list[tuple[str, str]]:
    datos = json.loads((DIR / "fewshot_banco.json").read_text(encoding="utf-8"))["ejemplos"]
    return [(e["pregunta"], e["sql"]) for e in datos]


@lru_cache(maxsize=1)
def _indice_tfidf():
    docs = [Counter(_tokens(p)) for p, _ in banco()]
    df = Counter(w for d in docs for w in d)
    n = len(docs)
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
    vecs = []
    for d in docs:
        v = {w: tf * idf[w] for w, tf in d.items()}
        norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norma for w, x in v.items()})
    return idf, vecs


def ejemplos_parecidos(pregunta: str, k: int = N_FEWSHOT_DINAMICO) -> list[tuple[str, str]]:
    idf, vecs = _indice_tfidf()
    q = Counter(_tokens(pregunta))
    v = {w: tf * idf.get(w, 0.0) for w, tf in q.items()}
    norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
    puntajes = [(sum(v.get(w, 0.0) * x for w, x in d.items()) / norma, -i) for i, d in enumerate(vecs)]
    mejores = sorted(range(len(vecs)), key=lambda i: puntajes[i], reverse=True)[:k]
    return [banco()[i] for i in mejores]


def texto_ejemplos(pregunta: str) -> str:
    return "Ejemplos de pregunta -> SQL correcto (parecidos a esta pregunta):\n\n" + "\n\n".join(
        f"Pregunta: {p}\nSQL: {s}" for p, s in ejemplos_parecidos(pregunta))


# --------------------------------------------------------------------- composición
def depende_de_la_pregunta() -> bool:
    return USAR_ESQUEMA_POR_PREGUNTA or USAR_FEWSHOT_DINAMICO


@lru_cache(maxsize=256)
def esquema_para(pregunta: str) -> str:
    """Contexto de esquema (system prompt) para esta pregunta según los interruptores E2/E5."""
    tablas = vistas = None
    if USAR_ESQUEMA_POR_PREGUNTA:
        tablas, vistas = seleccion_esquema(pregunta)
    return sc.build_schema_context(tablas=tablas, vistas_visibles=vistas, con_ejemplos=not USAR_FEWSHOT_DINAMICO)


def contexto_usuario(pregunta: str) -> str | None:
    """Bloques dinámicos que van en el prompt de USUARIO (así el system sigue siendo cacheable)."""
    partes = []
    if USAR_GLOSARIO:
        g = texto_glosario(pregunta)
        if g:
            partes.append(g)
    if USAR_FEWSHOT_DINAMICO:
        partes.append(texto_ejemplos(pregunta))
    return "\n\n".join(partes) or None


def todo_el_texto_opcional() -> str:
    """Todo lo que algún interruptor podría inyectar (para las pruebas de no-derivación)."""
    partes = [f"{e['termino']}: {e['definicion']}\n{e['sql']}" for e in glosario()]  # lo que se inyecta, no los disparadores
    partes += [f"{p}\n{s}" for p, s in banco()]
    partes.append(REGLA_PLAN)
    partes.append(sc.texto_descripciones_columnas())
    partes += [sc.VISTAS_NEGOCIO_DESCRIPCION[v] for v in sc.VISTAS_NEGOCIO_DESCRIPCION]
    return "\n".join(partes)
