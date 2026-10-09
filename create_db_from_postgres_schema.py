import sqlite3
import os

db_path = os.path.join("data", "asemaco_postgres.sqlite3")

# Si la base de datos ya existe, se podría borrar o avisar
if os.path.exists(db_path):
    print(f"La base de datos {db_path} ya existe. Eliminándola para crear una nueva.")
    os.remove(db_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Habilitar claves foráneas en SQLite
cursor.execute("PRAGMA foreign_keys = ON;")

schema = """
CREATE TABLE empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razon_social VARCHAR(300),
    nif VARCHAR(50),
    direccion VARCHAR(300),
    poblacion VARCHAR(200),
    pais VARCHAR(100),
    telefono VARCHAR(50),
    correo VARCHAR(254),
    logotipo VARCHAR(255)
);

CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER,
    correo VARCHAR(254) UNIQUE,
    contrasena VARCHAR(256),
    rol VARCHAR(20),
    activo BOOLEAN DEFAULT 1,
    debe_cambiar BOOLEAN DEFAULT 1,
    FOREIGN KEY(empresa_id) REFERENCES empresas(id)
);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    number INTEGER,
    token VARCHAR(100) UNIQUE,
    created DATETIME,
    data TEXT,
    pdf_sha256 VARCHAR(64),
    revoked BOOLEAN DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES usuarios(id)
);

CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    kind VARCHAR(50),
    data TEXT,
    FOREIGN KEY(user_id) REFERENCES usuarios(id)
);
"""

try:
    cursor.executescript(schema)
    conn.commit()
    print(f"Base de datos creada exitosamente en {db_path}")
except sqlite3.Error as e:
    print(f"Error al crear la base de datos: {e}")
finally:
    conn.close()
