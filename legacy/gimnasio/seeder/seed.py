"""
Seeder de datos sintéticos para la base de datos del gimnasio ficticio "FitZone".

Genera datos coherentes y con estacionalidad realista para todo el año 2025,
incluyendo nulos y outliers controlados a propósito (para poder medir después
qué tanto "alucina" o se equivoca un LLM frente a datos imperfectos).

El script es IDEMPOTENTE: por defecto, en cada corrida elimina todas las tablas
y las vuelve a crear antes de insertar datos nuevos (ver --no-reset para desactivar
este comportamiento).

Uso:
    python legacy/gimnasio/seeder/seed.py                          # cantidades por defecto
    python legacy/gimnasio/seeder/seed.py --clientes 3000 --scale 1.5
    python legacy/gimnasio/seeder/seed.py --seed 7                  # reproducibilidad distinta
    python legacy/gimnasio/seeder/seed.py --no-reset                # agrega datos sin limpiar (no recomendado)

Requiere: SQLAlchemy, Faker (ver requirements.txt)
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raíz del repositorio

from faker import Faker
from sqlalchemy import text

from legacy.gimnasio.db.database import engine
from legacy.gimnasio.db.init_db import create_schema, create_views, reset_schema
from legacy.gimnasio.db.models import (
    CalendarioEvento,
    CampaniaMarketing,
    Checkin,
    ClaseCatalogo,
    Cliente,
    Descuento,
    Equipo,
    EncuestaSatisfaccion,
    GastoOperativo,
    Instructor,
    Membresia,
    MovimientoInventario,
    OrdenMantenimiento,
    Pago,
    Producto,
    Proveedor,
    Reservacion,
    SesionClase,
    TicketSoporte,
    Venta,
)

# =============================================================================
# CONFIGURACION GENERAL
# =============================================================================
ANIO = 2025
FECHA_INICIO_ANIO = dt.date(ANIO, 1, 1)
FECHA_FIN_ANIO = dt.date(ANIO, 12, 31)
DIAS_EN_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # 2025 no es bisiesto

# Pesos de estacionalidad por mes (1 = promedio). Reflejan patrones típicos de
# gimnasios en México: pico en enero ("año nuevo, vida nueva"), caída en
# temporada vacacional (jul-ago), repunte en septiembre ("vuelta a la rutina").
PESOS_ASISTENCIA = {1: 1.70, 2: 1.30, 3: 1.05, 4: 0.95, 5: 0.85, 6: 0.75, 7: 0.65, 8: 0.70, 9: 1.15, 10: 1.05, 11: 0.95, 12: 0.95}
PESOS_ALTAS = {1: 2.30, 2: 1.40, 3: 1.00, 4: 0.80, 5: 0.75, 6: 0.70, 7: 0.65, 8: 0.75, 9: 1.30, 10: 0.95, 11: 0.85, 12: 1.15}
PESOS_LUZ = {1: 0.90, 2: 0.90, 3: 1.00, 4: 1.15, 5: 1.30, 6: 1.35, 7: 1.40, 8: 1.40, 9: 1.20, 10: 1.00, 11: 0.90, 12: 0.95}
PESOS_AGUA = {1: 0.95, 2: 0.95, 3: 1.00, 4: 1.05, 5: 1.15, 6: 1.20, 7: 1.20, 8: 1.15, 9: 1.05, 10: 1.00, 11: 0.95, 12: 0.95}

ZONAS_COLONIAS = {
    "Centro": ["Centro Histórico", "Roma Norte", "Condesa"],
    "Norte": ["Lindavista", "Satélite", "Industrial"],
    "Sur": ["Coyoacán", "Del Valle", "Narvarte"],
    "Poniente": ["Santa Fe", "Polanco", "Las Águilas"],
    "Oriente": ["Iztapalapa Centro", "Pantitlán", "Agrícola Oriental"],
}

CANALES_ADQUISICION = ["redes_sociales", "referido", "walk_in", "campania", "otro"]
PESOS_CANALES = [0.32, 0.22, 0.28, 0.13, 0.05]

MOTIVOS_CANCELACION = [
    "Cambio de residencia",
    "Motivos económicos",
    "Falta de tiempo",
    "Insatisfacción con el servicio",
    "Lesión o motivos de salud",
    "Cambio a otro gimnasio",
]
MOTIVOS_CONGELAMIENTO = ["Viaje prolongado", "Lesión temporal", "Motivos de salud", "Motivos laborales"]

PRECIOS_MEMBRESIA = {"mensual": (450, 600), "semestral": (2400, 3000), "anual": (4200, 5400)}
DURACION_MESES = {"mensual": 1, "semestral": 6, "anual": 12}
PESOS_TIPO_MEMBRESIA = {"mensual": 0.60, "semestral": 0.25, "anual": 0.15}

NOMBRES_CLASES = [
    ("Spinning", 22), ("CrossFit", 16), ("Yoga", 20), ("Zumba", 25), ("Box", 18),
    ("Funcional", 20), ("Pilates", 16), ("HIIT", 18), ("Step", 20), ("Aqua Aeróbics", 15),
    ("Calistenia", 15), ("Stretching", 20),
]

CATEGORIAS_PRODUCTOS = {
    "suplemento": [("Proteína Whey 2lb", (350, 550)), ("Creatina 300g", (250, 400)), ("BCAA 200g", (280, 420)),
                   ("Pre-entreno 300g", (320, 480)), ("Barra proteica", (25, 45)), ("Multivitamínico", (180, 300))],
    "ropa": [("Playera dry-fit", (180, 350)), ("Short deportivo", (220, 380)), ("Leggings", (280, 450)),
             ("Sudadera con capucha", (400, 650)), ("Calcetas deportivas", (60, 120))],
    "accesorio": [("Guantes de entrenamiento", (150, 280)), ("Cinturón de fuerza", (350, 600)),
                  ("Shaker", (80, 150)), ("Toalla deportiva", (90, 160)), ("Banda de resistencia", (120, 220)),
                  ("Straps de levantamiento", (140, 240))],
    "servicio": [("Evaluación física", (250, 400)), ("Plan nutricional", (400, 700)), ("Entrenamiento personal (sesión)", (300, 550))],
}

CATEGORIAS_EQUIPO = {
    "cardio": ["Caminadora", "Bicicleta fija", "Elíptica", "Remo"],
    "fuerza": ["Rack de sentadillas", "Banca plana", "Multiestación", "Prensa de piernas"],
    "funcional": ["Kettlebells (set)", "TRX", "Cajón pliométrico", "Cuerda de batalla"],
    "accesorio": ["Colchoneta", "Rodillo de espuma", "Mancuernas (par)"],
}

FERIADOS_2025 = [
    (dt.date(2025, 1, 1), "Año Nuevo", "feriado_nacional"),
    (dt.date(2025, 2, 3), "Día de la Constitución", "feriado_nacional"),
    (dt.date(2025, 3, 17), "Natalicio de Benito Juárez", "feriado_nacional"),
    (dt.date(2025, 5, 1), "Día del Trabajo", "feriado_nacional"),
    (dt.date(2025, 9, 16), "Día de la Independencia", "feriado_nacional"),
    (dt.date(2025, 11, 17), "Día de la Revolución Mexicana", "feriado_nacional"),
    (dt.date(2025, 12, 25), "Navidad", "feriado_nacional"),
]
EVENTOS_GIMNASIO_2025 = [
    (dt.date(2025, 1, 6), "Reto Año Nuevo, Vida Nueva", "evento_gimnasio", "Campaña de arranque de año con clases extra e inscripciones promocionales"),
    (dt.date(2025, 2, 14), "Clase especial San Valentín", "evento_gimnasio", "Clase temática en pareja"),
    (dt.date(2025, 5, 10), "Clase especial Día de las Madres", "evento_gimnasio", None),
    (dt.date(2025, 7, 1), "Mantenimiento mayor de equipo", "evento_gimnasio", "Cierre parcial por mantenimiento programado"),
    (dt.date(2025, 9, 15), "Aniversario del gimnasio", "evento_gimnasio", "Clases gratuitas y descuentos por aniversario"),
    (dt.date(2025, 12, 1), "Arranque Reto Fin de Año", "evento_gimnasio", "Campaña de retención y captación previa a año nuevo"),
]


def dia_aleatorio_en_mes(rng: random.Random, mes: int) -> dt.date:
    dia = rng.randint(1, DIAS_EN_MES[mes - 1])
    return dt.date(ANIO, mes, dia)


def mes_ponderado(rng: random.Random, pesos: dict[int, float]) -> int:
    meses = list(pesos.keys())
    pesos_lista = list(pesos.values())
    return rng.choices(meses, weights=pesos_lista, k=1)[0]


def poisson_sample(rng: random.Random, lam: float) -> int:
    """Muestreo Poisson simple (algoritmo de Knuth), suficiente para lambda pequeñas."""
    if lam <= 0:
        return 0
    l = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1


def bulk_insert(conn, table, rows: list[dict], chunk_size: int = 500):
    if not rows:
        return
    for i in range(0, len(rows), chunk_size):
        conn.execute(table, rows[i : i + chunk_size])


# =============================================================================
# GENERADORES POR ENTIDAD
# =============================================================================
def gen_proveedores(rng, fake, n):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "id": i,
            "nombre": fake.company(),
            "contacto": fake.name(),
            "telefono": fake.msisdn()[:10],
            "email": fake.company_email(),
        })
    return rows


def gen_productos(rng, fake, proveedor_ids):
    rows = []
    pid = 1
    for categoria, items in CATEGORIAS_PRODUCTOS.items():
        for nombre, (pmin, pmax) in items:
            costo = round(rng.uniform(pmin * 0.5, pmin * 0.75), 2)
            precio_venta = round(rng.uniform(pmin, pmax), 2)
            rows.append({
                "id": pid,
                "nombre": nombre,
                "categoria": categoria,
                "costo": costo,
                "precio_venta": precio_venta,
                "proveedor_id": rng.choice(proveedor_ids),
                "activo": True,
            })
            pid += 1
    return rows


def gen_equipos(rng, n):
    rows = []
    for i in range(1, n + 1):
        categoria = rng.choice(list(CATEGORIAS_EQUIPO.keys()))
        nombre = rng.choice(CATEGORIAS_EQUIPO[categoria])
        fecha_compra = dt.date(rng.randint(2019, 2025), rng.randint(1, 12), rng.randint(1, 28))
        costo = round(rng.uniform(3000, 45000), 2)
        vida_util = rng.choice([5, 7, 8, 10, 12])
        estado = rng.choices(["operativo", "en_reparacion", "baja"], weights=[0.90, 0.07, 0.03])[0]
        rows.append({
            "id": i, "nombre": nombre, "categoria": categoria, "fecha_compra": fecha_compra,
            "costo": costo, "vida_util_anios": vida_util, "estado": estado,
        })
    return rows


def gen_instructores(rng, fake, n):
    rows = []
    puestos = ["instructor_grupal", "entrenador_personal", "coordinador"]
    contratos = ["planta", "honorarios", "medio_tiempo"]
    for i in range(1, n + 1):
        fecha_contratacion = dt.date(rng.randint(2018, 2025), rng.randint(1, 12), rng.randint(1, 28))
        rows.append({
            "id": i, "nombre": fake.first_name(), "apellido": fake.last_name(),
            "puesto": rng.choices(puestos, weights=[0.6, 0.3, 0.1])[0],
            "fecha_contratacion": fecha_contratacion,
            "tipo_contrato": rng.choices(contratos, weights=[0.5, 0.3, 0.2])[0],
            "activo": rng.random() > 0.05,
        })
    return rows


def gen_clases_catalogo(rng, instructor_ids):
    rows = []
    for i, (nombre, capacidad) in enumerate(NOMBRES_CLASES, start=1):
        rows.append({
            "id": i, "nombre": nombre, "instructor_id": rng.choice(instructor_ids),
            "capacidad": capacidad, "duracion_minutos": rng.choice([45, 50, 60]),
        })
    return rows


def gen_campanias(rng, n):
    tipos = ["redes_sociales", "volanteo", "referidos", "evento", "google_ads"]
    rows = []
    for i in range(1, n + 1):
        mes_inicio = mes_ponderado(rng, PESOS_ALTAS)
        fecha_inicio = dia_aleatorio_en_mes(rng, mes_inicio)
        duracion = rng.randint(10, 45)
        fecha_fin = min(fecha_inicio + dt.timedelta(days=duracion), FECHA_FIN_ANIO)
        rows.append({
            "id": i,
            "nombre": f"Campaña {rng.choice(['Verano','Regreso a Clases','Año Nuevo','Aniversario','Reto Fitness','Referidos Dobles'])} {i}",
            "tipo": rng.choice(tipos),
            "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
            "costo": round(rng.uniform(2000, 18000), 2),
            "descripcion": None,
        })
    return rows


def gen_descuentos(rng, n, campania_ids):
    rows = []
    for i in range(1, n + 1):
        tipo = rng.choice(["porcentaje", "monto_fijo"])
        valor = round(rng.uniform(5, 30), 2) if tipo == "porcentaje" else round(rng.uniform(50, 300), 2)
        mes_inicio = rng.randint(1, 12)
        fecha_inicio = dia_aleatorio_en_mes(rng, mes_inicio)
        fecha_fin = min(fecha_inicio + dt.timedelta(days=rng.randint(15, 60)), FECHA_FIN_ANIO)
        rows.append({
            "id": i, "nombre": f"Promoción {i}", "tipo": tipo, "valor": valor,
            "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
            "campania_id": rng.choice(campania_ids) if rng.random() < 0.5 else None,
        })
    return rows


def gen_clientes(rng, fake, n, campania_ids):
    rows = []
    for i in range(1, n + 1):
        mes_alta = mes_ponderado(rng, PESOS_ALTAS)
        fecha_alta = dia_aleatorio_en_mes(rng, mes_alta)
        zona = rng.choice(list(ZONAS_COLONIAS.keys()))
        colonia = rng.choice(ZONAS_COLONIAS[zona])
        canal = rng.choices(CANALES_ADQUISICION, weights=PESOS_CANALES, k=1)[0]

        referido_por_id = None
        if canal == "referido" and i > 5:
            referido_por_id = rng.randint(1, i - 1)

        campania_id = None
        if canal == "campania" and campania_ids:
            campania_id = rng.choice(campania_ids)

        # --- nulos controlados (dato sintético imperfecto, a propósito) ---
        telefono = fake.msisdn()[:10] if rng.random() > 0.04 else None
        email = fake.free_email() if rng.random() > 0.03 else None
        colonia_val = colonia if rng.random() > 0.06 else None
        fecha_nacimiento = dt.date(rng.randint(1965, 2007), rng.randint(1, 12), rng.randint(1, 28)) if rng.random() > 0.02 else None

        rows.append({
            "id": i, "nombre": fake.first_name(), "apellido": fake.last_name(),
            "email": email, "telefono": telefono, "fecha_nacimiento": fecha_nacimiento,
            "genero": rng.choice(["F", "M", "otro"]),
            "zona": zona, "colonia": colonia_val, "fecha_alta": fecha_alta,
            "canal_adquisicion": canal, "referido_por_id": referido_por_id, "campania_id": campania_id,
        })
    return rows


def gen_membresias_y_pagos(rng, clientes_rows):
    """Simula el ciclo de vida de membresías (con renovaciones, cancelaciones y
    congelamientos) y genera en paralelo los pagos de cuota asociados a cada periodo."""
    membresias, pagos = [], []
    mem_id, pago_id = 1, 1

    for cliente in clientes_rows:
        cid = cliente["id"]
        tipo = rng.choices(list(PESOS_TIPO_MEMBRESIA.keys()), weights=list(PESOS_TIPO_MEMBRESIA.values()))[0]
        pmin, pmax = PRECIOS_MEMBRESIA[tipo]
        fecha_cursor = cliente["fecha_alta"]

        while fecha_cursor <= FECHA_FIN_ANIO:
            duracion_meses = DURACION_MESES[tipo]
            fecha_fin_periodo = fecha_cursor + dt.timedelta(days=30 * duracion_meses)
            precio = round(rng.uniform(pmin, pmax), 2)

            renovacion_prob = {"mensual": 0.80, "semestral": 0.72, "anual": 0.68}[tipo]
            congelamiento_prob = 0.06
            roll = rng.random()

            if roll < congelamiento_prob:
                estado = "congelada"
                fecha_fin_congelamiento = fecha_cursor + dt.timedelta(days=rng.randint(20, 60))
                membresias.append({
                    "id": mem_id, "cliente_id": cid, "tipo": tipo, "precio": precio,
                    "fecha_inicio": fecha_cursor, "fecha_fin": fecha_fin_congelamiento,
                    "fecha_renovacion": None, "estado": "congelada",
                    "motivo_cancelacion": None, "fecha_cancelacion": None,
                    "motivo_congelamiento": rng.choice(MOTIVOS_CONGELAMIENTO),
                })
                if fecha_cursor <= FECHA_FIN_ANIO:
                    monto = precio if rng.random() > 0.01 else None
                    pagos.append(_pago_row(pago_id, cid, mem_id, fecha_cursor, monto, tipo, rng))
                    pago_id += 1
                mem_id += 1
                fecha_cursor = fecha_fin_congelamiento
                continue

            if roll < congelamiento_prob + (1 - renovacion_prob):
                estado_final = "cancelada"
            else:
                is_last_period = fecha_fin_periodo > FECHA_FIN_ANIO
                estado_final = "activa" if is_last_period else "vencida"

            fecha_cancelacion = None
            motivo_cancelacion = None
            if estado_final == "cancelada":
                fecha_cancelacion = fecha_cursor + dt.timedelta(days=rng.randint(3, max(4, duracion_meses * 20)))
                fecha_cancelacion = min(fecha_cancelacion, FECHA_FIN_ANIO)
                motivo_cancelacion = rng.choice(MOTIVOS_CANCELACION)

            membresias.append({
                "id": mem_id, "cliente_id": cid, "tipo": tipo, "precio": precio,
                "fecha_inicio": fecha_cursor, "fecha_fin": fecha_fin_periodo,
                "fecha_renovacion": fecha_fin_periodo if estado_final != "cancelada" else None,
                "estado": estado_final, "motivo_cancelacion": motivo_cancelacion,
                "fecha_cancelacion": fecha_cancelacion, "motivo_congelamiento": None,
            })

            monto = precio if rng.random() > 0.01 else None
            if rng.random() < 0.005:
                monto = round(rng.uniform(8000, 15000), 2)  # outlier: cobro duplicado / error de captura
            pagos.append(_pago_row(pago_id, cid, mem_id, fecha_cursor, monto, tipo, rng))
            pago_id += 1

            mem_id += 1
            if estado_final == "cancelada":
                break
            fecha_cursor = fecha_fin_periodo

    return membresias, pagos


def _pago_row(pago_id, cliente_id, membresia_id, fecha, monto, tipo_membresia, rng):
    concepto = {"mensual": "cuota_mensual", "semestral": "cuota_semestral", "anual": "cuota_anual"}[tipo_membresia]
    return {
        "id": pago_id, "cliente_id": cliente_id, "membresia_id": membresia_id,
        "fecha_pago": fecha, "monto": monto,
        "metodo_pago": rng.choices(["tarjeta", "efectivo", "transferencia"], weights=[0.55, 0.30, 0.15])[0],
        "concepto": concepto, "descuento_id": None,
    }


def gen_ventas_y_movimientos(rng, n_ventas, producto_rows, cliente_ids, proveedor_ids, descuento_ids):
    ventas, movimientos = [], []
    venta_id, mov_id = 1, 1

    productos_por_id = {p["id"]: p for p in producto_rows}
    producto_ids = list(productos_por_id.keys())

    # Entradas de inventario (compras a proveedor), ~1 por producto por mes
    for producto_id in producto_ids:
        for mes in range(1, 13):
            movimientos.append({
                "id": mov_id, "producto_id": producto_id, "tipo": "entrada",
                "cantidad": rng.randint(10, 60), "fecha": dia_aleatorio_en_mes(rng, mes),
                "proveedor_id": productos_por_id[producto_id]["proveedor_id"], "motivo": "compra",
            })
            mov_id += 1

    for _ in range(n_ventas):
        mes = mes_ponderado(rng, PESOS_ASISTENCIA)
        fecha = dia_aleatorio_en_mes(rng, mes)
        producto_id = rng.choice(producto_ids)
        precio_unitario = productos_por_id[producto_id]["precio_venta"]
        if rng.random() < 0.003:
            precio_unitario = 0.0  # outlier: error de captura en punto de venta
        cantidad = rng.choices([1, 2, 3, 4], weights=[0.6, 0.25, 0.1, 0.05])[0]
        cliente_id = rng.choice(cliente_ids) if rng.random() > 0.10 else None  # 10% ventas a visitantes
        descuento_id = rng.choice(descuento_ids) if rng.random() < 0.15 else None

        ventas.append({
            "id": venta_id, "cliente_id": cliente_id, "producto_id": producto_id, "fecha": fecha,
            "cantidad": cantidad, "precio_unitario": precio_unitario, "descuento_id": descuento_id,
        })
        movimientos.append({
            "id": mov_id, "producto_id": producto_id, "tipo": "salida", "cantidad": cantidad,
            "fecha": fecha, "proveedor_id": None, "motivo": "venta",
        })
        venta_id += 1
        mov_id += 1

    return ventas, movimientos


def gen_gastos_operativos(rng):
    rows = []
    gid = 1
    for mes in range(1, 13):
        fecha = dt.date(ANIO, mes, rng.randint(1, 5))  # los servicios suelen facturarse a inicio de mes

        luz = round(rng.uniform(700, 1400) * PESOS_LUZ[mes], 2)
        luz = max(500, min(luz, 2000))
        if mes == 7:
            luz = round(rng.uniform(4800, 6000), 2)  # outlier: falla de aire acondicionado en julio
        agua = round(rng.uniform(500, 900) * PESOS_AGUA[mes], 2)
        agua = max(500, min(agua, 2000))
        internet = round(rng.uniform(650, 900), 2)

        rows.append({"id": gid, "categoria": "servicios_basicos", "subcategoria": "luz", "monto": luz, "fecha": fecha,
                      "descripcion": "Consumo eléctrico mensual" if mes != 7 else "Consumo eléctrico mensual (pico por falla de A/C)"})
        gid += 1
        rows.append({"id": gid, "categoria": "servicios_basicos", "subcategoria": "agua", "monto": agua, "fecha": fecha, "descripcion": "Consumo de agua mensual"})
        gid += 1
        rows.append({"id": gid, "categoria": "servicios_basicos", "subcategoria": "internet", "monto": internet, "fecha": fecha, "descripcion": "Servicio de internet y telefonía"})
        gid += 1

        limpieza = round(rng.uniform(1800, 3200), 2)
        rows.append({"id": gid, "categoria": "mantenimiento_limpieza", "subcategoria": "insumos_limpieza", "monto": limpieza, "fecha": fecha, "descripcion": "Insumos de limpieza y sanitización"})
        gid += 1

        nomina = round(rng.uniform(85000, 110000), 2)
        rows.append({"id": gid, "categoria": "nomina", "subcategoria": "nomina_general", "monto": nomina, "fecha": fecha, "descripcion": "Nómina agregada del personal (no incluye desglose individual)"})
        gid += 1

        renta = round(rng.uniform(28000, 32000), 2)
        rows.append({"id": gid, "categoria": "renta", "subcategoria": "renta_local", "monto": renta, "fecha": fecha, "descripcion": "Renta mensual del local"})
        gid += 1

    return rows


def gen_ordenes_mantenimiento(rng, equipo_rows, n):
    rows = []
    equipo_ids = [e["id"] for e in equipo_rows]
    for i in range(1, n + 1):
        equipo_id = rng.choice(equipo_ids)
        mes = rng.randint(1, 12)
        rows.append({
            "id": i, "equipo_id": equipo_id, "fecha": dia_aleatorio_en_mes(rng, mes),
            "tipo": rng.choices(["preventivo", "correctivo"], weights=[0.6, 0.4])[0],
            "costo": round(rng.uniform(300, 6000), 2),
            "descripcion": rng.choice(["Revisión programada", "Cambio de bandas/cables", "Reparación de motor",
                                        "Lubricación general", "Ajuste de calibración", "Sustitución de piezas desgastadas"]),
        })
    return rows


def gen_sesiones_y_reservaciones_y_checkins(rng, clases_rows, cliente_rows):
    sesiones, reservaciones, checkins_clase, encuestas = [], [], [], []
    sesion_id, res_id, checkin_id, encuesta_id = 1, 1, 1, 1

    clientes_por_fecha_alta = sorted(cliente_rows, key=lambda c: c["fecha_alta"])
    horarios = ["07:00", "09:00", "12:00", "18:00", "19:30"]
    dias_semana_por_clase = {c["id"]: sorted(rng.sample(range(7), k=rng.choice([3, 4, 5]))) for c in clases_rows}

    fecha = FECHA_INICIO_ANIO
    while fecha <= FECHA_FIN_ANIO:
        weekday = fecha.weekday()
        mes = fecha.month
        clientes_disponibles = [c["id"] for c in clientes_por_fecha_alta if c["fecha_alta"] <= fecha]

        for clase in clases_rows:
            if weekday not in dias_semana_por_clase[clase["id"]]:
                continue
            hora_inicio = rng.choice(horarios)
            h, m = map(int, hora_inicio.split(":"))
            fin_dt = (dt.datetime(2000, 1, 1, h, m) + dt.timedelta(minutes=clase["duracion_minutos"])).time()

            sesiones.append({
                "id": sesion_id, "clase_id": clase["id"], "instructor_id": clase["instructor_id"],
                "fecha": fecha, "hora_inicio": hora_inicio, "hora_fin": fin_dt.strftime("%H:%M"),
                "capacidad": clase["capacidad"], "sala": rng.choice(["Sala A", "Sala B", "Área Funcional", "Alberca"]),
            })

            demanda = clase["capacidad"] * rng.uniform(0.4, 1.05) * PESOS_ASISTENCIA[mes]
            n_reservaciones = min(clase["capacidad"], max(0, round(demanda)))
            if clientes_disponibles and n_reservaciones > 0:
                asistentes = rng.sample(clientes_disponibles, k=min(n_reservaciones, len(clientes_disponibles)))
                for cliente_id in asistentes:
                    estado = rng.choices(["asistio", "no_show", "cancelado"], weights=[0.72, 0.18, 0.10])[0]
                    reservaciones.append({
                        "id": res_id, "sesion_id": sesion_id, "cliente_id": cliente_id,
                        "fecha_reservacion": fecha - dt.timedelta(days=rng.randint(0, 5)),
                        "estado": estado,
                    })
                    res_id += 1

                    if estado == "asistio":
                        checkins_clase.append({
                            "id": checkin_id, "cliente_id": cliente_id, "fecha": fecha, "hora": hora_inicio,
                            "tipo": "clase", "sesion_id": sesion_id,
                        })
                        checkin_id += 1
                        if rng.random() < 0.22:
                            calificacion = rng.choices(range(0, 11), weights=[1,1,1,1,2,3,5,10,20,25,20])[0]
                            comentario = None
                            if calificacion <= 4 and rng.random() < 0.6:
                                comentario = rng.choice([
                                    "El instructor llegó tarde", "Faltó equipo disponible", "Sala muy llena",
                                    "No cumplió mis expectativas", "Música muy alta",
                                ])
                            elif calificacion >= 9 and rng.random() < 0.4:
                                comentario = rng.choice([
                                    "Excelente clase, muy energética", "El instructor es muy profesional",
                                    "Me encantó, seguiré viniendo", "Muy buena rutina",
                                ])
                            encuestas.append({
                                "id": encuesta_id, "cliente_id": cliente_id, "sesion_id": sesion_id,
                                "fecha": fecha, "calificacion": calificacion, "comentario": comentario,
                            })
                            encuesta_id += 1

            sesion_id += 1
        fecha += dt.timedelta(days=1)

    return sesiones, reservaciones, checkins_clase, encuestas, checkin_id


def gen_checkins_libres(rng, cliente_rows, membresias_rows, checkin_id_inicial):
    checkins = []
    checkin_id = checkin_id_inicial

    intervalos_activos = {}
    for m in membresias_rows:
        if m["estado"] == "congelada":
            continue
        cid = m["cliente_id"]
        fin = m["fecha_fin"] or FECHA_FIN_ANIO
        if m["estado"] == "cancelada" and m["fecha_cancelacion"]:
            fin = m["fecha_cancelacion"]
        intervalos_activos.setdefault(cid, []).append((m["fecha_inicio"], min(fin, FECHA_FIN_ANIO)))

    horas_operacion = [f"{h:02d}:{m:02d}" for h in range(6, 22) for m in (0, 20, 40)]

    for cliente in cliente_rows:
        cid = cliente["id"]
        intervalos = intervalos_activos.get(cid, [])
        if not intervalos:
            continue
        engagement_semanal = rng.uniform(0.15, 1.3)

        for inicio, fin in intervalos:
            if fin < inicio:
                continue
            semana_actual = inicio
            while semana_actual <= fin:
                fin_semana = min(semana_actual + dt.timedelta(days=6), fin)
                mes = semana_actual.month
                lam = engagement_semanal * PESOS_ASISTENCIA[mes]
                n_visitas = min(6, poisson_sample(rng, lam))
                dias_disponibles = (fin_semana - semana_actual).days + 1
                for _ in range(n_visitas):
                    offset = rng.randint(0, max(0, dias_disponibles - 1))
                    fecha_visita = semana_actual + dt.timedelta(days=offset)
                    checkins.append({
                        "id": checkin_id, "cliente_id": cid, "fecha": fecha_visita,
                        "hora": rng.choice(horas_operacion), "tipo": "entrenamiento_libre", "sesion_id": None,
                    })
                    checkin_id += 1
                semana_actual = fin_semana + dt.timedelta(days=1)

    return checkins


def gen_tickets_soporte(rng, cliente_ids, n):
    categorias = ["equipo", "limpieza", "atencion", "cobros", "instalaciones", "otro"]
    rows = []
    for i in range(1, n + 1):
        mes = rng.randint(1, 12)
        fecha_apertura = dia_aleatorio_en_mes(rng, mes)
        estado = rng.choices(["cerrado", "en_proceso", "abierto"], weights=[0.75, 0.15, 0.10])[0]
        fecha_cierre = fecha_apertura + dt.timedelta(days=rng.randint(1, 20)) if estado == "cerrado" else None
        if fecha_cierre and fecha_cierre > FECHA_FIN_ANIO:
            fecha_cierre = FECHA_FIN_ANIO
        rows.append({
            "id": i, "cliente_id": rng.choice(cliente_ids), "fecha_apertura": fecha_apertura,
            "categoria": rng.choice(categorias), "estado": estado,
            "descripcion": rng.choice(["Máquina fuera de servicio", "Vestidor sucio", "Mala atención en recepción",
                                        "Cobro duplicado en tarjeta", "Aire acondicionado no funciona", "Consulta general"]),
            "fecha_cierre": fecha_cierre,
        })
    return rows


def gen_calendario(rng):
    rows = []
    cid = 1
    for fecha, nombre, tipo in FERIADOS_2025:
        rows.append({"id": cid, "fecha": fecha, "nombre_evento": nombre, "tipo": tipo, "descripcion": None})
        cid += 1
    for fecha, nombre, tipo, desc in EVENTOS_GIMNASIO_2025:
        rows.append({"id": cid, "fecha": fecha, "nombre_evento": nombre, "tipo": tipo, "descripcion": desc})
        cid += 1
    return rows


# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Genera datos sintéticos para la base de datos del gimnasio (año 2025).")
    parser.add_argument("--clientes", type=int, default=1800, help="Número de clientes a generar (default: 1800)")
    parser.add_argument("--scale", type=float, default=1.0, help="Factor de escala para tablas transaccionales (default: 1.0)")
    parser.add_argument("--seed", type=int, default=42, help="Semilla aleatoria para reproducibilidad (default: 42)")
    parser.add_argument("--no-reset", action="store_true", help="No limpiar la base de datos antes de sembrar (no recomendado)")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    fake = Faker("es_MX")
    fake.seed_instance(args.seed)

    print(f"=== Seeder FitZone {ANIO} | clientes={args.clientes} scale={args.scale} seed={args.seed} ===")

    if not args.no_reset:
        print("Limpiando y recreando esquema...")
        reset_schema()
    create_schema()
    create_views()

    with engine.begin() as conn:
        print("Generando catálogos base (proveedores, productos, equipos, instructores, clases)...")
        proveedores = gen_proveedores(rng, fake, 12)
        bulk_insert(conn, Proveedor.__table__.insert(), proveedores)

        productos = gen_productos(rng, fake, [p["id"] for p in proveedores])
        bulk_insert(conn, Producto.__table__.insert(), productos)

        equipos = gen_equipos(rng, 50)
        bulk_insert(conn, Equipo.__table__.insert(), equipos)

        instructores = gen_instructores(rng, fake, 20)
        bulk_insert(conn, Instructor.__table__.insert(), instructores)

        clases = gen_clases_catalogo(rng, [i["id"] for i in instructores])
        bulk_insert(conn, ClaseCatalogo.__table__.insert(), clases)

        campanias = gen_campanias(rng, 10)
        bulk_insert(conn, CampaniaMarketing.__table__.insert(), campanias)

        descuentos = gen_descuentos(rng, 15, [c["id"] for c in campanias])
        bulk_insert(conn, Descuento.__table__.insert(), descuentos)

        calendario = gen_calendario(rng)
        bulk_insert(conn, CalendarioEvento.__table__.insert(), calendario)

        print(f"Generando {args.clientes} clientes...")
        clientes = gen_clientes(rng, fake, args.clientes, [c["id"] for c in campanias])
        bulk_insert(conn, Cliente.__table__.insert(), clientes)

        print("Simulando ciclo de vida de membresías y pagos...")
        membresias, pagos = gen_membresias_y_pagos(rng, clientes)
        bulk_insert(conn, Membresia.__table__.insert(), membresias)
        bulk_insert(conn, Pago.__table__.insert(), pagos)
        print(f"  -> {len(membresias)} membresías, {len(pagos)} pagos")

        n_ventas = int(8000 * args.scale)
        print(f"Generando ~{n_ventas} ventas y movimientos de inventario...")
        ventas, movimientos = gen_ventas_y_movimientos(
            rng, n_ventas, productos, [c["id"] for c in clientes], [p["id"] for p in proveedores], [d["id"] for d in descuentos]
        )
        bulk_insert(conn, Venta.__table__.insert(), ventas)
        bulk_insert(conn, MovimientoInventario.__table__.insert(), movimientos)
        print(f"  -> {len(ventas)} ventas, {len(movimientos)} movimientos de inventario")

        print("Generando gastos operativos mensuales...")
        gastos = gen_gastos_operativos(rng)
        bulk_insert(conn, GastoOperativo.__table__.insert(), gastos)

        n_ordenes = int(130 * args.scale)
        ordenes = gen_ordenes_mantenimiento(rng, equipos, n_ordenes)
        bulk_insert(conn, OrdenMantenimiento.__table__.insert(), ordenes)

        print("Generando calendario de sesiones de clase, reservaciones, check-ins de clase y encuestas...")
        sesiones, reservaciones, checkins_clase, encuestas, siguiente_checkin_id = gen_sesiones_y_reservaciones_y_checkins(rng, clases, clientes)
        bulk_insert(conn, SesionClase.__table__.insert(), sesiones)
        bulk_insert(conn, Reservacion.__table__.insert(), reservaciones)
        bulk_insert(conn, Checkin.__table__.insert(), checkins_clase)
        bulk_insert(conn, EncuestaSatisfaccion.__table__.insert(), encuestas)
        print(f"  -> {len(sesiones)} sesiones, {len(reservaciones)} reservaciones, {len(checkins_clase)} check-ins de clase, {len(encuestas)} encuestas")

        print("Generando check-ins de entrenamiento libre (esto puede tardar unos segundos)...")
        checkins_libres = gen_checkins_libres(rng, clientes, membresias, siguiente_checkin_id)
        bulk_insert(conn, Checkin.__table__.insert(), checkins_libres)
        print(f"  -> {len(checkins_libres)} check-ins libres")

        n_tickets = int(300 * args.scale)
        tickets = gen_tickets_soporte(rng, [c["id"] for c in clientes], n_tickets)
        bulk_insert(conn, TicketSoporte.__table__.insert(), tickets)

    print("\n=== Resumen de registros por tabla ===")
    with engine.connect() as conn:
        tablas = [
            "clientes", "membresias", "pagos", "productos", "ventas", "movimientos_inventario",
            "proveedores", "equipos", "gastos_operativos", "ordenes_mantenimiento", "instructores",
            "clases_catalogo", "sesiones_clase", "reservaciones", "checkins", "campanias_marketing",
            "descuentos", "encuestas_satisfaccion", "tickets_soporte", "calendario_eventos",
        ]
        for t in tablas:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t:28s} {count:>8,}")

    print("\nSeed completado con éxito.")


if __name__ == "__main__":
    main()
