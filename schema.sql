-- ============================================================
-- Esquema PostgreSQL: Sistema Contable (Libro Mayor & Diario)
-- ============================================================
-- Ejecutar como: psql -U contable_user -d contable_db -f schema.sql

CREATE TABLE IF NOT EXISTS compras (
    id              VARCHAR(40) PRIMARY KEY,
    fecha           DATE NOT NULL,
    comprobante     VARCHAR(60) NOT NULL,
    proveedor       VARCHAR(150) NOT NULL,
    ruc             VARCHAR(20),
    descripcion     VARCHAR(250),
    base            NUMERIC(14,2) NOT NULL CHECK (base >= 0),
    igv             NUMERIC(14,2) NOT NULL CHECK (igv >= 0),
    total           NUMERIC(14,2) NOT NULL CHECK (total >= 0),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ventas (
    id              VARCHAR(40) PRIMARY KEY,
    fecha           DATE NOT NULL,
    tipo_comprobante VARCHAR(20) NOT NULL DEFAULT 'Factura' CHECK (tipo_comprobante IN ('Factura','Boleta')),
    comprobante     VARCHAR(60) NOT NULL,
    cliente         VARCHAR(150) NOT NULL,
    ruc             VARCHAR(20),
    descripcion     VARCHAR(250),
    base            NUMERIC(14,2) NOT NULL CHECK (base >= 0),
    igv             NUMERIC(14,2) NOT NULL CHECK (igv >= 0),
    total           NUMERIC(14,2) NOT NULL CHECK (total >= 0),
    costo           NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (costo >= 0),
    retencion       NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (retencion >= 0),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- La retención (12%) solo puede existir si el comprobante es Factura
    CONSTRAINT retencion_solo_factura CHECK (retencion = 0 OR tipo_comprobante = 'Factura')
);

CREATE TABLE IF NOT EXISTS asientos_iniciales (
    id              VARCHAR(40) PRIMARY KEY,
    fecha           DATE NOT NULL,
    glosa           VARCHAR(300) NOT NULL,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asientos_iniciales_lineas (
    id              SERIAL PRIMARY KEY,
    asiento_id      VARCHAR(40) NOT NULL REFERENCES asientos_iniciales(id) ON DELETE CASCADE,
    cuenta          VARCHAR(20) NOT NULL,
    nombre          VARCHAR(150) NOT NULL,
    naturaleza      CHAR(1) NOT NULL CHECK (naturaleza IN ('D','H')),
    debe            NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (debe >= 0),
    haber           NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (haber >= 0)
);

CREATE TABLE IF NOT EXISTS planillas (
    id              VARCHAR(40) PRIMARY KEY,
    fecha           DATE NOT NULL,
    periodo         VARCHAR(20) NOT NULL,
    trabajador      VARCHAR(150) NOT NULL,
    dni             VARCHAR(20),
    cargo           VARCHAR(100),
    sueldo_bruto    NUMERIC(14,2) NOT NULL CHECK (sueldo_bruto >= 0),
    essalud         NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (essalud >= 0),
    sistema_pension VARCHAR(10) NOT NULL DEFAULT 'ONP' CHECK (sistema_pension IN ('ONP','AFP','NINGUNO')),
    aporte_pension  NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (aporte_pension >= 0),
    renta_5ta       NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (renta_5ta >= 0),
    otros_descuentos NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (otros_descuentos >= 0),
    neto_pagar      NUMERIC(14,2) NOT NULL CHECK (neto_pagar >= 0),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Autenticación: un administrador por instalación (el usuario que
-- reciba el enlace crea su propio usuario/clave la primera vez que
-- abre el sistema).
-- ============================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id              VARCHAR(40) PRIMARY KEY,
    usuario         VARCHAR(60) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sesiones (
    token           VARCHAR(64) PRIMARY KEY,
    usuario_id      VARCHAR(40) NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en       TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_compras_fecha ON compras(fecha);
CREATE INDEX IF NOT EXISTS idx_compras_ruc ON compras(ruc);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_ruc ON ventas(ruc);
CREATE INDEX IF NOT EXISTS idx_asientos_iniciales_fecha ON asientos_iniciales(fecha);
CREATE INDEX IF NOT EXISTS idx_lineas_asiento_id ON asientos_iniciales_lineas(asiento_id);
CREATE INDEX IF NOT EXISTS idx_planillas_fecha ON planillas(fecha);
CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones(usuario_id);
