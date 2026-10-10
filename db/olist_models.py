"""
Modelos ORM (SQLAlchemy 2.x) para la base de datos de e-commerce Olist
(dataset público brasileño, ver data/olist/ y https://www.kaggle.com/olistbr).

Diseño portable: igual que db/models.py, se usan tipos genéricos de SQLAlchemy
(Integer, String, Numeric, DateTime, Text) que se traducen automáticamente a los
tipos nativos tanto de SQLite como de PostgreSQL.

Convenciones y particularidades importantes del dataset (ver también
docs/esquema_olist.md para la versión pensada para el prompt del LLM):
  - `customer_id` es único POR PEDIDO, no por persona. La persona real está
    identificada por `customer_unique_id` (puede repetirse en varias filas de
    `customers`, una por cada pedido que hizo esa persona). Cualquier pregunta
    sobre "clientes recurrentes" o "clientes únicos" debe agrupar por
    `customer_unique_id`, nunca por `customer_id`.
  - `geolocation` NO tiene llave natural única: hay muchas filas por
    `geolocation_zip_code_prefix` (distintas lat/lng dentro del mismo prefijo
    postal). Se usa un `id` autoincremental solo como PK técnica de la tabla.
  - `order_reviews` tiene `review_id` con valores duplicados (el mismo id
    reaparece en pedidos distintos) y varios pedidos tienen más de una reseña.
    Por eso tampoco tiene llave natural única; se usa `id` autoincremental como
    PK y `review_id` queda como columna indexada, no única.
  - Los códigos postales (`*_zip_code_prefix`) se guardan como `String`, no
    `Integer`, para no perder ceros a la izquierda (ej. "01037").
  - `products.product_category_name` NO tiene FK formal hacia
    `product_category_translation`: la tabla de traducción no cubre todas las
    categorías presentes en `products`, así que un FK estricto rompería la
    carga. La relación es solo lógica, se resuelve con LEFT JOIN.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class OlistBase(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# CATALOGOS INDEPENDIENTES
# ---------------------------------------------------------------------------
class Seller(OlistBase):
    """Vendedores del marketplace."""

    __tablename__ = "sellers"

    seller_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seller_zip_code_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    seller_city: Mapped[str] = mapped_column(String(80), nullable=False)
    seller_state: Mapped[str] = mapped_column(String(2), nullable=False)

    __table_args__ = (Index("ix_sellers_zip", "seller_zip_code_prefix"),)


class Customer(OlistBase):
    """Una fila por pedido (ver nota de módulo: `customer_id` != persona real)."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_unique_id: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="Identificador real de la persona; se repite entre pedidos"
    )
    customer_zip_code_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    customer_city: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_state: Mapped[str] = mapped_column(String(2), nullable=False)

    __table_args__ = (
        Index("ix_customers_unique_id", "customer_unique_id"),
        Index("ix_customers_zip", "customer_zip_code_prefix"),
    )


class ProductCategoryTranslation(OlistBase):
    """Traducción portugués -> inglés del nombre de categoría (cobertura incompleta)."""

    __tablename__ = "product_category_translation"

    product_category_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_category_name_english: Mapped[str] = mapped_column(String(80), nullable=False)


class Product(OlistBase):
    """Catálogo de productos. Conserva los typos originales del dataset
    (`lenght` en vez de `length`) para no desincronizar de la fuente; se
    documentan en docs/esquema_olist.md."""

    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_category_name: Mapped[str | None] = mapped_column(
        String(80), nullable=True, comment="Nombre en portugués; sin FK formal, ver nota de módulo"
    )
    product_name_lenght: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="typo original del dataset: 'lenght'")
    product_description_lenght: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="typo original del dataset: 'lenght'")
    product_photos_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_length_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_width_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_products_category", "product_category_name"),)


class Geolocation(OlistBase):
    """Coordenadas por prefijo de código postal. Sin llave natural única (ver
    nota de módulo): `id` es una PK técnica, no viene del CSV."""

    __tablename__ = "geolocation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    geolocation_zip_code_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    geolocation_lat: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    geolocation_lng: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    geolocation_city: Mapped[str] = mapped_column(String(80), nullable=False)
    geolocation_state: Mapped[str] = mapped_column(String(2), nullable=False)

    __table_args__ = (Index("ix_geolocation_zip", "geolocation_zip_code_prefix"),)


# ---------------------------------------------------------------------------
# PEDIDOS
# ---------------------------------------------------------------------------
class Order(OlistBase):
    """Pedido. Las fechas de aprobación/envío/entrega quedan NULL cuando el
    pedido no llegó a esa etapa (ej. `order_status` = 'canceled')."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("customers.customer_id"), nullable=False)
    order_status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="delivered | shipped | canceled | unavailable | invoiced | processing | created | approved"
    )
    order_purchase_timestamp: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    order_approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    order_delivered_carrier_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    order_delivered_customer_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True, comment="NULL si el pedido no fue entregado (ver order_status)"
    )
    order_estimated_delivery_date: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)

    customer: Mapped["Customer"] = relationship()

    __table_args__ = (
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_status", "order_status"),
        Index("ix_orders_purchase_ts", "order_purchase_timestamp"),
    )


class OrderItem(OlistBase):
    """Línea de producto dentro de un pedido. PK compuesta: un pedido puede
    tener varios `order_item_id` (uno por unidad/línea vendida)."""

    __tablename__ = "order_items"

    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.order_id"), primary_key=True)
    order_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.product_id"), nullable=False)
    seller_id: Mapped[str] = mapped_column(String(32), ForeignKey("sellers.seller_id"), nullable=False)
    shipping_limit_date: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    freight_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped["Order"] = relationship()
    product: Mapped["Product"] = relationship()
    seller: Mapped["Seller"] = relationship()

    __table_args__ = (
        Index("ix_order_items_product_id", "product_id"),
        Index("ix_order_items_seller_id", "seller_id"),
    )


class OrderPayment(OlistBase):
    """Pago(s) de un pedido. PK compuesta: un pedido puede pagarse en varias
    transacciones/secuencias (`payment_sequential`), ej. tarjeta + voucher."""

    __tablename__ = "order_payments"

    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.order_id"), primary_key=True)
    payment_sequential: Mapped[int] = mapped_column(Integer, primary_key=True, comment="Columna original del CSV: payment_sequential")
    payment_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="credit_card | boleto | voucher | debit_card | not_defined")
    payment_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped["Order"] = relationship()

    __table_args__ = (Index("ix_order_payments_type", "payment_type"),)


class OrderReview(OlistBase):
    """Reseña de un pedido. `review_id` NO es único (ver nota de módulo); un
    mismo pedido puede tener más de una reseña. `id` es la PK técnica."""

    __tablename__ = "order_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="No es único, ver nota de módulo")
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.order_id"), nullable=False)
    review_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="Escala 1-5")
    review_comment_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_comment_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_creation_date: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    review_answer_timestamp: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)

    order: Mapped["Order"] = relationship()

    __table_args__ = (
        Index("ix_order_reviews_order_id", "order_id"),
        Index("ix_order_reviews_review_id", "review_id"),
        Index("ix_order_reviews_score", "review_score"),
    )
