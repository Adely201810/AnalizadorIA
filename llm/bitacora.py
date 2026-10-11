"""
Bitácora persistente de errores de esquema (Fase 10).

Cuando el modelo usa una columna o tabla que no existe (detectado por
llm/sql_guard.py o por SQLite), se registra aquí con una corrección concreta
(dónde existe esa columna de verdad). En preguntas FUTURAS, las entradas más
frecuentes y recientes se añaden al prompt del generador para que no repita
el error.

- Es un archivo JSON propio (por defecto runtime/bitacora_esquema.json, fuera
  de git; configurable con TEXT2SQL_BITACORA). NUNCA se escribe en las tablas
  de Olist.
- Límites para no contaminar el prompt ni crecer sin control: como mucho
  MAX_ENTRADAS en el archivo (se descartan las menos recientes), MAX_BYTES de
  archivo y MAX_INYECTADAS entradas de hasta MAX_CHARS_ENTRADA caracteres en el
  prompt.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

RUTA_DEFECTO = Path(os.environ.get(
    "TEXT2SQL_BITACORA", Path(__file__).resolve().parent.parent / "runtime" / "bitacora_esquema.json"
))
MAX_ENTRADAS = 100
MAX_BYTES = 64_000
MAX_INYECTADAS = 5
MAX_CHARS_ENTRADA = 220

_NO_SUCH = re.compile(r"no such (column|table): ([\w.]+)", re.I)


def detalles_de_error(exc: Exception, esquema_real: dict[str, set[str]]) -> list[dict]:
    """Errores de esquema estructurados a partir de la excepción (o [] si no lo es)."""
    detalles = getattr(exc, "detalles", None)
    if detalles:
        return detalles
    if isinstance(exc, sqlite3.Error):
        m = _NO_SUCH.search(str(exc))
        if m:
            nombre = m.group(2).lower()
            if m.group(1).lower() == "table":
                return [{"tipo": "tabla", "nombre": nombre}]
            tabla, _, columna = nombre.rpartition(".")
            donde = sorted(t for t, cols in esquema_real.items() if columna in cols)
            return [{"tipo": "columna", "tabla": tabla or None, "columna": columna, "existe_en": donde}]
    return []


def _clave_y_mensaje(d: dict) -> tuple[str, str]:
    if d["tipo"] == "tabla":
        return f"tabla:{d['nombre']}", f"La tabla/vista '{d['nombre']}' no existe en el esquema."
    donde = d.get("existe_en") or []
    lugar = f"está en: {', '.join(donde)}" if donde else "no existe en ninguna tabla ni vista"
    if d.get("tabla"):
        return (f"columna:{d['tabla']}.{d['columna']}",
                f"La columna '{d['columna']}' no existe en '{d['tabla']}'; {lugar}.")
    return f"columna:*.{d['columna']}", f"La columna '{d['columna']}' {lugar}."


class BitacoraEsquema:
    def __init__(self, ruta: Path | str | None = None, max_entradas: int = MAX_ENTRADAS,
                 max_inyectadas: int = MAX_INYECTADAS, max_bytes: int = MAX_BYTES):
        self.ruta = Path(ruta) if ruta else RUTA_DEFECTO
        self.max_entradas, self.max_inyectadas, self.max_bytes = max_entradas, max_inyectadas, max_bytes

    def entradas(self) -> list[dict]:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))["entradas"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return []

    def _guardar(self, entradas: list[dict]) -> None:
        entradas = sorted(entradas, key=lambda e: e["ultima"], reverse=True)[: self.max_entradas]
        while True:
            texto = json.dumps({"version": 1, "entradas": entradas}, ensure_ascii=False, indent=2)
            if len(texto.encode("utf-8")) <= self.max_bytes or not entradas:
                break
            entradas = entradas[:-1]  # descarta la menos reciente
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(texto, encoding="utf-8")
        tmp.replace(self.ruta)

    def registrar(self, detalles: list[dict], pregunta: str) -> list[str]:
        """Suma una aparición por cada error de esquema. Devuelve las claves registradas."""
        if not detalles:
            return []
        ahora = datetime.now().isoformat(timespec="seconds")
        por_clave = {e["clave"]: e for e in self.entradas()}
        claves = []
        for d in detalles:
            clave, mensaje = _clave_y_mensaje(d)
            if clave in claves:
                continue  # la misma columna repetida en un SQL (SELECT y GROUP BY) cuenta una vez
            e = por_clave.get(clave)
            if e:
                e["veces"] += 1
                e["ultima"] = ahora
            else:
                por_clave[clave] = {"clave": clave, "mensaje": mensaje[:MAX_CHARS_ENTRADA], "veces": 1,
                                    "primera": ahora, "ultima": ahora, "ejemplo_pregunta": pregunta[:120]}
            claves.append(clave)
        self._guardar(list(por_clave.values()))
        return claves

    def texto_para_prompt(self) -> str | None:
        """Las MAX_INYECTADAS entradas más frecuentes (y, a igualdad, más recientes)."""
        top = sorted(self.entradas(), key=lambda e: (e["veces"], e["ultima"]), reverse=True)[: self.max_inyectadas]
        if not top:
            return None
        return ("Errores de esquema cometidos en consultas anteriores (no los repitas):\n"
                + "\n".join(f"- {e['mensaje'][:MAX_CHARS_ENTRADA]}" for e in top))
