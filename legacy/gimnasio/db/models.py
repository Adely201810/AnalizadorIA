"""
Modelos ORM (SQLAlchemy 2.x) para la base de datos del gimnasio ficticio "FitZone".

Diseño portable: se usan tipos genéricos de SQLAlchemy (Integer, String, Numeric,
Date, DateTime, Boolean, Text) que se traducen automáticamente a los tipos nativos
tanto de SQLite como de PostgreSQL. Para migrar a PostgreSQL basta con cambiar la
variable de entorno DATABASE_URL (ver legacy/gimnasio/db/database.py) y correr legacy/gimnasio/db/init_db.py contra
el nuevo motor -- no hay SQL específico de SQLite en este archivo.

Convenciones:
  - Todas las tablas usan `id` entero autoincremental como PK.
  - Fechas de negocio (fecha_alta, fecha_pago, etc.) usan Date; timestamps de
    sistema usan DateTime.
  - Los montos monetarios usan Numeric(10, 2) y están en pesos mexicanos (MXN).
  - Las FK que pueden quedar nulas (ej. referido_por_id) representan relaciones
    opcionales del negocio, no errores de datos.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# CLIENTES / MEMBRESIAS
# ---------------------------------------------------------------------------
class Cliente(Base):
    """Clientes del gimnasio: datos demográficos y de adquisición."""

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    apellido: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_nacimiento: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    genero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    zona: Mapped[str | None] = mapped_column(String(80), nullable=True, comment="Zona/región de la ciudad")
    colonia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_alta: Mapped[dt.date] = mapped_column(Date, nullable=False, comment="Fecha en la que se dio de alta como cliente")
    canal_adquisicion: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="redes_sociales | referido | walk_in | campania | otro"
    )
    referido_por_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clientes.id"), nullable=True, comment="Self-FK: cliente que lo refirió, si aplica"
    )
    campania_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campanias_marketing.id"), nullable=True, comment="Campaña de marketing asociada al alta"
    )

    referido_por: Mapped["Cliente | None"] = relationship(remote_side=[id])

    __table_args__ = (
        Index("ix_clientes_fecha_alta", "fecha_alta"),
        Index("ix_clientes_canal_adquisicion", "canal_adquisicion"),
    )


class Membresia(Base):
    """Historial de membresías por cliente (un cliente puede tener varias a través del año)."""

    __tablename__ = "membresias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, comment="mensual | semestral | anual")
    precio: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date | None] = mapped_column(Date, nullable=True, comment="Fecha en que vence/venció el periodo contratado")
    fecha_renovacion: Mapped[dt.date | None] = mapped_column(Date, nullable=True, comment="Próxima fecha de renovación esperada")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, comment="activa | cancelada | congelada | vencida")
    motivo_cancelacion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fecha_cancelacion: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    motivo_congelamiento: Mapped[str | None] = mapped_column(String(200), nullable=True)

    cliente: Mapped["Cliente"] = relationship()

    __table_args__ = (
        Index("ix_membresias_cliente_id", "cliente_id"),
        Index("ix_membresias_estado", "estado"),
        Index("ix_membresias_fecha_inicio", "fecha_inicio"),
    )


# ---------------------------------------------------------------------------
# INGRESOS / TRANSACCIONES
# ---------------------------------------------------------------------------
class Descuento(Base):
    """Catálogo de descuentos y promociones que se pueden aplicar a pagos o ventas."""

    __tablename__ = "descuentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, comment="porcentaje | monto_fijo")
    valor: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    campania_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("campanias_marketing.id"), nullable=True)


class Pago(Base):
    """Pagos de cuotas/membresías y cobros recurrentes."""

    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)
    membresia_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("membresias.id"), nullable=True)
    fecha_pago: Mapped[dt.date] = mapped_column(Date, nullable=False)
    monto: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Puede ser NULL por error de captura (dato sintético intencional)"
    )
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False, comment="efectivo | tarjeta | transferencia")
    concepto: Mapped[str] = mapped_column(String(30), nullable=False, comment="cuota_mensual | cuota_semestral | cuota_anual | otro")
    descuento_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("descuentos.id"), nullable=True)

    cliente: Mapped["Cliente"] = relationship()
    membresia: Mapped["Membresia | None"] = relationship()

    __table_args__ = (
        Index("ix_pagos_cliente_id", "cliente_id"),
        Index("ix_pagos_fecha_pago", "fecha_pago"),
    )


class Producto(Base):
    """Catálogo de productos/servicios adicionales (suplementos, ropa, accesorios)."""

    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False, comment="suplemento | ropa | accesorio | servicio")
    costo: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    precio_venta: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    proveedor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("proveedores.id"), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    proveedor: Mapped["Proveedor | None"] = relationship()


class Venta(Base):
    """Ventas de productos/servicios adicionales a clientes (o visitantes ocasionales)."""

    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=True, comment="NULL si fue venta a visitante sin membresía")
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_unitario: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    descuento_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("descuentos.id"), nullable=True)

    cliente: Mapped["Cliente | None"] = relationship()
    producto: Mapped["Producto"] = relationship()

    __table_args__ = (
        Index("ix_ventas_fecha", "fecha"),
        Index("ix_ventas_producto_id", "producto_id"),
    )


# ---------------------------------------------------------------------------
# GASTOS OPERATIVOS
# ---------------------------------------------------------------------------
class GastoOperativo(Base):
    """
    Gastos operativos del gimnasio: servicios básicos, mantenimiento/limpieza,
    nómina agregada (sin desglose de sueldos individuales) y otros gastos fijos.
    """

    __tablename__ = "gastos_operativos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoria: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="servicios_basicos | mantenimiento_limpieza | nomina | renta | otro"
    )
    subcategoria: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="Ej: agua | luz | internet | insumos_limpieza | nomina_general"
    )
    monto: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_gastos_operativos_fecha", "fecha"),
        Index("ix_gastos_operativos_categoria", "categoria"),
    )


class Equipo(Base):
    """Catálogo de equipo/máquinas del gimnasio."""

    __tablename__ = "equipos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False, comment="cardio | fuerza | funcional | accesorio")
    fecha_compra: Mapped[dt.date] = mapped_column(Date, nullable=False)
    costo: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    vida_util_anios: Mapped[int] = mapped_column(Integer, nullable=False, comment="Vida útil estimada en años")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="operativo", comment="operativo | en_reparacion | baja")


class OrdenMantenimiento(Base):
    """Órdenes de mantenimiento/reparación de equipo."""

    __tablename__ = "ordenes_mantenimiento"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipo_id: Mapped[int] = mapped_column(Integer, ForeignKey("equipos.id"), nullable=False)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, comment="preventivo | correctivo")
    costo: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    equipo: Mapped["Equipo"] = relationship()

    __table_args__ = (Index("ix_ordenes_mantenimiento_fecha", "fecha"),)


# ---------------------------------------------------------------------------
# PERSONAL
# ---------------------------------------------------------------------------
class Instructor(Base):
    """Instructores/entrenadores (sin montos de sueldo, solo datos laborales generales)."""

    __tablename__ = "instructores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    apellido: Mapped[str] = mapped_column(String(80), nullable=False)
    puesto: Mapped[str] = mapped_column(String(60), nullable=False, comment="instructor_grupal | entrenador_personal | coordinador")
    fecha_contratacion: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tipo_contrato: Mapped[str] = mapped_column(String(20), nullable=False, comment="planta | honorarios | medio_tiempo")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Proveedor(Base):
    """Proveedores de productos e insumos."""

    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    contacto: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)


# ---------------------------------------------------------------------------
# CLASES Y ASISTENCIA
# ---------------------------------------------------------------------------
class ClaseCatalogo(Base):
    """Catálogo de tipos de clase (spinning, crossfit, yoga, etc.), horario base e instructor por defecto."""

    __tablename__ = "clases_catalogo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False, comment="spinning | crossfit | yoga | zumba | box | funcional...")
    instructor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("instructores.id"), nullable=True, comment="Instructor titular")
    capacidad: Mapped[int] = mapped_column(Integer, nullable=False)
    duracion_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    instructor: Mapped["Instructor | None"] = relationship()


class SesionClase(Base):
    """Instancia concreta de una clase en el calendario (fecha/hora reales, capacidad e instructor asignado)."""

    __tablename__ = "sesiones_clase"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clase_id: Mapped[int] = mapped_column(Integer, ForeignKey("clases_catalogo.id"), nullable=False)
    instructor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("instructores.id"), nullable=True)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora_inicio: Mapped[str] = mapped_column(String(5), nullable=False, comment="Formato HH:MM")
    hora_fin: Mapped[str] = mapped_column(String(5), nullable=False)
    capacidad: Mapped[int] = mapped_column(Integer, nullable=False)
    sala: Mapped[str | None] = mapped_column(String(40), nullable=True)

    clase: Mapped["ClaseCatalogo"] = relationship()
    instructor: Mapped["Instructor | None"] = relationship()

    __table_args__ = (
        Index("ix_sesiones_clase_fecha", "fecha"),
        Index("ix_sesiones_clase_clase_id", "clase_id"),
    )


class Reservacion(Base):
    """Reservaciones de clientes a sesiones de clase, incluyendo no-shows."""

    __tablename__ = "reservaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sesion_id: Mapped[int] = mapped_column(Integer, ForeignKey("sesiones_clase.id"), nullable=False)
    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha_reservacion: Mapped[dt.date] = mapped_column(Date, nullable=False, comment="Fecha en que se hizo la reservación")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, comment="reservado | asistio | no_show | cancelado")

    sesion: Mapped["SesionClase"] = relationship()
    cliente: Mapped["Cliente"] = relationship()

    __table_args__ = (
        UniqueConstraint("sesion_id", "cliente_id", name="uq_reservacion_sesion_cliente"),
        Index("ix_reservaciones_estado", "estado"),
    )


class Checkin(Base):
    """Registro de check-ins/asistencia diaria al gimnasio (con o sin clase asociada)."""

    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora: Mapped[str] = mapped_column(String(5), nullable=False, comment="Formato HH:MM")
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, comment="entrenamiento_libre | clase")
    sesion_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sesiones_clase.id"), nullable=True)

    cliente: Mapped["Cliente"] = relationship()

    __table_args__ = (
        Index("ix_checkins_fecha", "fecha"),
        Index("ix_checkins_cliente_id", "cliente_id"),
    )


# ---------------------------------------------------------------------------
# INVENTARIO
# ---------------------------------------------------------------------------
class MovimientoInventario(Base):
    """Movimientos de inventario: entradas por compra a proveedor, salidas por venta."""

    __tablename__ = "movimientos_inventario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, comment="entrada | salida")
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    proveedor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("proveedores.id"), nullable=True)
    motivo: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="compra | venta | merma | ajuste")

    producto: Mapped["Producto"] = relationship()
    proveedor: Mapped["Proveedor | None"] = relationship()

    __table_args__ = (Index("ix_movimientos_inventario_fecha", "fecha"),)


# ---------------------------------------------------------------------------
# MARKETING
# ---------------------------------------------------------------------------
class CampaniaMarketing(Base):
    """Campañas de marketing, relacionadas con nuevas altas de clientes en su periodo."""

    __tablename__ = "campanias_marketing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, comment="redes_sociales | volanteo | referidos | evento | google_ads")
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date] = mapped_column(Date, nullable=False)
    costo: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# SATISFACCION
# ---------------------------------------------------------------------------
class EncuestaSatisfaccion(Base):
    """Encuestas de satisfacción/NPS post-clase. Solo calificación numérica y comentario opcional."""

    __tablename__ = "encuestas_satisfaccion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=True)
    sesion_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sesiones_clase.id"), nullable=True)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    calificacion: Mapped[int] = mapped_column(Integer, nullable=False, comment="Escala NPS 0-10")
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_encuestas_satisfaccion_fecha", "fecha"),)


class TicketSoporte(Base):
    """Tickets de soporte/quejas de clientes."""

    __tablename__ = "tickets_soporte"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha_apertura: Mapped[dt.date] = mapped_column(Date, nullable=False)
    categoria: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="equipo | limpieza | atencion | cobros | instalaciones | otro"
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, comment="abierto | en_proceso | cerrado")
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_cierre: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (Index("ix_tickets_soporte_fecha_apertura", "fecha_apertura"),)


# ---------------------------------------------------------------------------
# CALENDARIO
# ---------------------------------------------------------------------------
class CalendarioEvento(Base):
    """Días festivos y eventos especiales del gimnasio, para correlacionar con picos de asistencia/ventas."""

    __tablename__ = "calendario_eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    nombre_evento: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, comment="feriado_nacional | evento_gimnasio")
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("ix_calendario_eventos_fecha", "fecha"),)
