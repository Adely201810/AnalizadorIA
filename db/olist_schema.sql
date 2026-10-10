-- DDL exportado automáticamente desde db/olist_models.py (SQLAlchemy) --

CREATE TABLE customers (
	customer_id VARCHAR(32) NOT NULL, 
	customer_unique_id VARCHAR(32) NOT NULL, 
	customer_zip_code_prefix VARCHAR(10) NOT NULL, 
	customer_city VARCHAR(80) NOT NULL, 
	customer_state VARCHAR(2) NOT NULL, 
	PRIMARY KEY (customer_id)
);

CREATE TABLE geolocation (
	id INTEGER NOT NULL, 
	geolocation_zip_code_prefix VARCHAR(10) NOT NULL, 
	geolocation_lat NUMERIC(11, 8) NOT NULL, 
	geolocation_lng NUMERIC(11, 8) NOT NULL, 
	geolocation_city VARCHAR(80) NOT NULL, 
	geolocation_state VARCHAR(2) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE product_category_translation (
	product_category_name VARCHAR(80) NOT NULL, 
	product_category_name_english VARCHAR(80) NOT NULL, 
	PRIMARY KEY (product_category_name)
);

CREATE TABLE products (
	product_id VARCHAR(32) NOT NULL, 
	product_category_name VARCHAR(80), 
	product_name_lenght INTEGER, 
	product_description_lenght INTEGER, 
	product_photos_qty INTEGER, 
	product_weight_g INTEGER, 
	product_length_cm INTEGER, 
	product_height_cm INTEGER, 
	product_width_cm INTEGER, 
	PRIMARY KEY (product_id)
);

CREATE TABLE sellers (
	seller_id VARCHAR(32) NOT NULL, 
	seller_zip_code_prefix VARCHAR(10) NOT NULL, 
	seller_city VARCHAR(80) NOT NULL, 
	seller_state VARCHAR(2) NOT NULL, 
	PRIMARY KEY (seller_id)
);

CREATE TABLE orders (
	order_id VARCHAR(32) NOT NULL, 
	customer_id VARCHAR(32) NOT NULL, 
	order_status VARCHAR(20) NOT NULL, 
	order_purchase_timestamp DATETIME NOT NULL, 
	order_approved_at DATETIME, 
	order_delivered_carrier_date DATETIME, 
	order_delivered_customer_date DATETIME, 
	order_estimated_delivery_date DATETIME NOT NULL, 
	PRIMARY KEY (order_id), 
	FOREIGN KEY(customer_id) REFERENCES customers (customer_id)
);

CREATE TABLE order_items (
	order_id VARCHAR(32) NOT NULL, 
	order_item_id INTEGER NOT NULL, 
	product_id VARCHAR(32) NOT NULL, 
	seller_id VARCHAR(32) NOT NULL, 
	shipping_limit_date DATETIME NOT NULL, 
	price NUMERIC(10, 2) NOT NULL, 
	freight_value NUMERIC(10, 2) NOT NULL, 
	PRIMARY KEY (order_id, order_item_id), 
	FOREIGN KEY(order_id) REFERENCES orders (order_id), 
	FOREIGN KEY(product_id) REFERENCES products (product_id), 
	FOREIGN KEY(seller_id) REFERENCES sellers (seller_id)
);

CREATE TABLE order_payments (
	order_id VARCHAR(32) NOT NULL, 
	payment_sequential INTEGER NOT NULL, 
	payment_type VARCHAR(20) NOT NULL, 
	payment_installments INTEGER NOT NULL, 
	payment_value NUMERIC(10, 2) NOT NULL, 
	PRIMARY KEY (order_id, payment_sequential), 
	FOREIGN KEY(order_id) REFERENCES orders (order_id)
);

CREATE TABLE order_reviews (
	id INTEGER NOT NULL, 
	review_id VARCHAR(32) NOT NULL, 
	order_id VARCHAR(32) NOT NULL, 
	review_score INTEGER NOT NULL, 
	review_comment_title VARCHAR(120), 
	review_comment_message TEXT, 
	review_creation_date DATETIME NOT NULL, 
	review_answer_timestamp DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (order_id)
);
