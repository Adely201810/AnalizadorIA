-- DDL exportado automáticamente desde db/models.py (SQLAlchemy) --

CREATE TABLE calendario_eventos (
	id INTEGER NOT NULL, 
	fecha DATE NOT NULL, 
	nombre_evento VARCHAR(150) NOT NULL, 
	tipo VARCHAR(30) NOT NULL, 
	descripcion VARCHAR(255), 
	PRIMARY KEY (id)
);

CREATE TABLE campanias_marketing (
	id INTEGER NOT NULL, 
	nombre VARCHAR(150) NOT NULL, 
	tipo VARCHAR(30) NOT NULL, 
	fecha_inicio DATE NOT NULL, 
	fecha_fin DATE NOT NULL, 
	costo NUMERIC(10, 2) NOT NULL, 
	descripcion VARCHAR(255), 
	PRIMARY KEY (id)
);

CREATE TABLE equipos (
	id INTEGER NOT NULL, 
	nombre VARCHAR(150) NOT NULL, 
	categoria VARCHAR(40) NOT NULL, 
	fecha_compra DATE NOT NULL, 
	costo NUMERIC(10, 2) NOT NULL, 
	vida_util_anios INTEGER NOT NULL, 
	estado VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE gastos_operativos (
	id INTEGER NOT NULL, 
	categoria VARCHAR(30) NOT NULL, 
	subcategoria VARCHAR(40), 
	monto NUMERIC(10, 2) NOT NULL, 
	fecha DATE NOT NULL, 
	descripcion VARCHAR(255), 
	PRIMARY KEY (id)
);

CREATE TABLE instructores (
	id INTEGER NOT NULL, 
	nombre VARCHAR(80) NOT NULL, 
	apellido VARCHAR(80) NOT NULL, 
	puesto VARCHAR(60) NOT NULL, 
	fecha_contratacion DATE NOT NULL, 
	tipo_contrato VARCHAR(20) NOT NULL, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE proveedores (
	id INTEGER NOT NULL, 
	nombre VARCHAR(150) NOT NULL, 
	contacto VARCHAR(120), 
	telefono VARCHAR(20), 
	email VARCHAR(150), 
	PRIMARY KEY (id)
);

CREATE TABLE clases_catalogo (
	id INTEGER NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	instructor_id INTEGER, 
	capacidad INTEGER NOT NULL, 
	duracion_minutos INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(instructor_id) REFERENCES instructores (id)
);

CREATE TABLE clientes (
	id INTEGER NOT NULL, 
	nombre VARCHAR(80) NOT NULL, 
	apellido VARCHAR(80) NOT NULL, 
	email VARCHAR(150), 
	telefono VARCHAR(20), 
	fecha_nacimiento DATE, 
	genero VARCHAR(20), 
	zona VARCHAR(80), 
	colonia VARCHAR(120), 
	fecha_alta DATE NOT NULL, 
	canal_adquisicion VARCHAR(30) NOT NULL, 
	referido_por_id INTEGER, 
	campania_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(referido_por_id) REFERENCES clientes (id), 
	FOREIGN KEY(campania_id) REFERENCES campanias_marketing (id)
);

CREATE TABLE descuentos (
	id INTEGER NOT NULL, 
	nombre VARCHAR(120) NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	valor NUMERIC(10, 2) NOT NULL, 
	fecha_inicio DATE NOT NULL, 
	fecha_fin DATE, 
	campania_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(campania_id) REFERENCES campanias_marketing (id)
);

CREATE TABLE ordenes_mantenimiento (
	id INTEGER NOT NULL, 
	equipo_id INTEGER NOT NULL, 
	fecha DATE NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	costo NUMERIC(10, 2) NOT NULL, 
	descripcion VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(equipo_id) REFERENCES equipos (id)
);

CREATE TABLE productos (
	id INTEGER NOT NULL, 
	nombre VARCHAR(150) NOT NULL, 
	categoria VARCHAR(40) NOT NULL, 
	costo NUMERIC(10, 2) NOT NULL, 
	precio_venta NUMERIC(10, 2) NOT NULL, 
	proveedor_id INTEGER, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(proveedor_id) REFERENCES proveedores (id)
);

CREATE TABLE membresias (
	id INTEGER NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	precio NUMERIC(10, 2) NOT NULL, 
	fecha_inicio DATE NOT NULL, 
	fecha_fin DATE, 
	fecha_renovacion DATE, 
	estado VARCHAR(20) NOT NULL, 
	motivo_cancelacion VARCHAR(200), 
	fecha_cancelacion DATE, 
	motivo_congelamiento VARCHAR(200), 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id)
);

CREATE TABLE movimientos_inventario (
	id INTEGER NOT NULL, 
	producto_id INTEGER NOT NULL, 
	tipo VARCHAR(10) NOT NULL, 
	cantidad INTEGER NOT NULL, 
	fecha DATE NOT NULL, 
	proveedor_id INTEGER, 
	motivo VARCHAR(60), 
	PRIMARY KEY (id), 
	FOREIGN KEY(producto_id) REFERENCES productos (id), 
	FOREIGN KEY(proveedor_id) REFERENCES proveedores (id)
);

CREATE TABLE sesiones_clase (
	id INTEGER NOT NULL, 
	clase_id INTEGER NOT NULL, 
	instructor_id INTEGER, 
	fecha DATE NOT NULL, 
	hora_inicio VARCHAR(5) NOT NULL, 
	hora_fin VARCHAR(5) NOT NULL, 
	capacidad INTEGER NOT NULL, 
	sala VARCHAR(40), 
	PRIMARY KEY (id), 
	FOREIGN KEY(clase_id) REFERENCES clases_catalogo (id), 
	FOREIGN KEY(instructor_id) REFERENCES instructores (id)
);

CREATE TABLE tickets_soporte (
	id INTEGER NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	fecha_apertura DATE NOT NULL, 
	categoria VARCHAR(40) NOT NULL, 
	estado VARCHAR(20) NOT NULL, 
	descripcion TEXT, 
	fecha_cierre DATE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id)
);

CREATE TABLE ventas (
	id INTEGER NOT NULL, 
	cliente_id INTEGER, 
	producto_id INTEGER NOT NULL, 
	fecha DATE NOT NULL, 
	cantidad INTEGER NOT NULL, 
	precio_unitario NUMERIC(10, 2) NOT NULL, 
	descuento_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id), 
	FOREIGN KEY(producto_id) REFERENCES productos (id), 
	FOREIGN KEY(descuento_id) REFERENCES descuentos (id)
);

CREATE TABLE checkins (
	id INTEGER NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	fecha DATE NOT NULL, 
	hora VARCHAR(5) NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	sesion_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id), 
	FOREIGN KEY(sesion_id) REFERENCES sesiones_clase (id)
);

CREATE TABLE encuestas_satisfaccion (
	id INTEGER NOT NULL, 
	cliente_id INTEGER, 
	sesion_id INTEGER, 
	fecha DATE NOT NULL, 
	calificacion INTEGER NOT NULL, 
	comentario TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id), 
	FOREIGN KEY(sesion_id) REFERENCES sesiones_clase (id)
);

CREATE TABLE pagos (
	id INTEGER NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	membresia_id INTEGER, 
	fecha_pago DATE NOT NULL, 
	monto NUMERIC(10, 2), 
	metodo_pago VARCHAR(20) NOT NULL, 
	concepto VARCHAR(30) NOT NULL, 
	descuento_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id), 
	FOREIGN KEY(membresia_id) REFERENCES membresias (id), 
	FOREIGN KEY(descuento_id) REFERENCES descuentos (id)
);

CREATE TABLE reservaciones (
	id INTEGER NOT NULL, 
	sesion_id INTEGER NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	fecha_reservacion DATE NOT NULL, 
	estado VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_reservacion_sesion_cliente UNIQUE (sesion_id, cliente_id), 
	FOREIGN KEY(sesion_id) REFERENCES sesiones_clase (id), 
	FOREIGN KEY(cliente_id) REFERENCES clientes (id)
);
