"""
API del Sistema Contable (Libro Mayor & Diario)
------------------------------------------------
Expone endpoints REST para que el frontend (index.html) guarde y lea
compras, ventas y asientos de apertura desde una base de datos PostgreSQL.

Ejecutar:
    uvicorn app:app --reload --port 8000
"""
import hashlib
import os
import pathlib
import secrets
import uuid
from datetime import date
from typing import List, Optional

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE_DIR = pathlib.Path(__file__).resolve().parent

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5435"),
    "dbname": os.getenv("DB_NAME", "contable_db"),
    "user": os.getenv("DB_USER", "contable_user"),
    "password": os.getenv("DB_PASSWORD", "cambia_esta_clave"),
}


def get_conn():
    try:
        return psycopg.connect(row_factory=dict_row, **DB_CONFIG)
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo conectar a PostgreSQL: {e}")


app = FastAPI(title="API Sistema Contable", version="1.0.0")

# Permite que el frontend (abierto como archivo local o en otro puerto) llame a la API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Autenticación (el usuario que reciba el enlace crea su propio admin)
# ---------------------------------------------------------------------------
PBKDF2_ITERACIONES = 200_000


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERACIONES)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hexhash = stored.split("$", 1)
    except ValueError:
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERACIONES)
    return secrets.compare_digest(h.hex(), hexhash)


def crear_sesion(cur, usuario_id: str) -> str:
    token = secrets.token_hex(32)
    cur.execute(
        "INSERT INTO sesiones (token, usuario_id, expira_en) VALUES (%s,%s, now() + interval '30 days')",
        (token, usuario_id),
    )
    return token


def usuario_actual(authorization: Optional[str] = Header(None)):
    """Dependencia que exige una sesión válida (token Bearer) para las rutas protegidas."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No autenticado. Inicia sesión.")
    token = authorization.split(" ", 1)[1].strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.token, u.id AS usuario_id, u.usuario
               FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
               WHERE s.token = %s AND s.expira_en > now()""",
            (token,),
        )
        fila = cur.fetchone()
        if not fila:
            raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Vuelve a iniciar sesión.")
        return fila


class ConfigurarAdmin(BaseModel):
    usuario: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=6, max_length=200)


class LoginRequest(BaseModel):
    usuario: str
    password: str


@app.get("/api/auth/estado")
def estado_auth():
    """Indica si ya existe un administrador configurado en esta instalación."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM usuarios")
        return {"configurado": cur.fetchone()["n"] > 0}


@app.post("/api/auth/configurar")
def configurar_admin(datos: ConfigurarAdmin):
    """Crea el primer (y único) usuario administrador. Solo funciona si todavía no hay ninguno."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM usuarios")
        if cur.fetchone()["n"] > 0:
            raise HTTPException(status_code=400, detail="Ya existe un administrador configurado. Inicia sesión.")
        nuevo_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO usuarios (id, usuario, password_hash) VALUES (%s,%s,%s)",
            (nuevo_id, datos.usuario.strip(), hash_password(datos.password)),
        )
        token = crear_sesion(cur, nuevo_id)
        conn.commit()
        return {"token": token, "usuario": datos.usuario.strip()}


@app.post("/api/auth/login")
def login(datos: LoginRequest):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM usuarios WHERE usuario = %s", (datos.usuario.strip(),))
        u = cur.fetchone()
        if not u or not verify_password(datos.password, u["password_hash"]):
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
        token = crear_sesion(cur, u["id"])
        conn.commit()
        return {"token": token, "usuario": u["usuario"]}


@app.post("/api/auth/logout")
def logout(actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sesiones WHERE token = %s", (actual["token"],))
        conn.commit()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class Compra(BaseModel):
    id: Optional[str] = None
    fecha: date
    comprobante: str
    proveedor: str
    ruc: Optional[str] = ""
    descripcion: Optional[str] = ""
    base: float = Field(gt=0)
    igv: float
    total: float


class Venta(BaseModel):
    id: Optional[str] = None
    fecha: date
    tipo_comprobante: str = "Factura"
    comprobante: str
    cliente: str
    ruc: Optional[str] = ""
    descripcion: Optional[str] = ""
    base: float = Field(gt=0)
    igv: float
    total: float
    costo: float = 0
    retencion: float = 0

    def validar_retencion(self):
        if self.retencion > 0 and self.tipo_comprobante != "Factura":
            raise HTTPException(
                status_code=400,
                detail="La retención del 12% solo puede aplicarse a comprobantes tipo Factura.",
            )
        esperado = round(self.total * 0.12, 2)
        if self.retencion not in (0, esperado):
            raise HTTPException(
                status_code=400,
                detail=f"La retención debe ser 0 o el 12% del total ({esperado}).",
            )


class Planilla(BaseModel):
    id: Optional[str] = None
    fecha: date
    periodo: str
    trabajador: str
    dni: Optional[str] = ""
    cargo: Optional[str] = ""
    sueldo_bruto: float = Field(gt=0)
    essalud: float = 0
    sistema_pension: str = "ONP"  # ONP | AFP | NINGUNO
    aporte_pension: float = 0
    renta_5ta: float = 0
    otros_descuentos: float = 0
    neto_pagar: float = Field(ge=0)

    def validar(self):
        if self.sistema_pension not in ("ONP", "AFP", "NINGUNO"):
            raise HTTPException(status_code=400, detail="Sistema de pensión inválido (usa ONP, AFP o NINGUNO).")


class LineaAsiento(BaseModel):
    cuenta: str
    nombre: str
    naturaleza: str  # 'D' o 'H'
    debe: float = 0
    haber: float = 0


class AsientoInicial(BaseModel):
    id: Optional[str] = None
    fecha: date
    glosa: str
    lineas: List[LineaAsiento]

    def validar_cuadre(self):
        total_debe = round(sum(l.debe for l in self.lineas), 2)
        total_haber = round(sum(l.haber for l in self.lineas), 2)
        if len(self.lineas) < 2:
            raise HTTPException(status_code=400, detail="El asiento debe tener al menos dos líneas.")
        if abs(total_debe - total_haber) >= 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"El asiento no cuadra: Debe={total_debe} Haber={total_haber}",
            )


# ---------------------------------------------------------------------------
# Compras
# ---------------------------------------------------------------------------
@app.get("/api/compras")
def listar_compras(actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM compras ORDER BY fecha, creado_en")
        return cur.fetchall()


@app.post("/api/compras")
def crear_compra(c: Compra, actual=Depends(usuario_actual)):
    nuevo_id = c.id or str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO compras (id, fecha, comprobante, proveedor, ruc, descripcion, base, igv, total)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (nuevo_id, c.fecha, c.comprobante, c.proveedor, c.ruc, c.descripcion, c.base, c.igv, c.total),
        )
        conn.commit()
        return cur.fetchone()


@app.delete("/api/compras/{compra_id}")
def eliminar_compra(compra_id: str, actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM compras WHERE id = %s", (compra_id,))
        conn.commit()
        return {"eliminado": cur.rowcount > 0}


# ---------------------------------------------------------------------------
# Ventas
# ---------------------------------------------------------------------------
@app.get("/api/ventas")
def listar_ventas(actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ventas ORDER BY fecha, creado_en")
        return cur.fetchall()


@app.post("/api/ventas")
def crear_venta(v: Venta, actual=Depends(usuario_actual)):
    v.validar_retencion()
    nuevo_id = v.id or str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ventas (id, fecha, tipo_comprobante, comprobante, cliente, ruc,
                                    descripcion, base, igv, total, costo, retencion)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (nuevo_id, v.fecha, v.tipo_comprobante, v.comprobante, v.cliente, v.ruc,
             v.descripcion, v.base, v.igv, v.total, v.costo, v.retencion),
        )
        conn.commit()
        return cur.fetchone()


@app.delete("/api/ventas/{venta_id}")
def eliminar_venta(venta_id: str, actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ventas WHERE id = %s", (venta_id,))
        conn.commit()
        return {"eliminado": cur.rowcount > 0}


@app.get("/api/ventas/buscar-por-ruc/{ruc}")
def buscar_ventas_por_ruc(ruc: str, actual=Depends(usuario_actual)):
    """Devuelve todas las facturas/boletas emitidas a un cliente, por su RUC/DNI."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ventas WHERE ruc = %s ORDER BY fecha, creado_en", (ruc.strip(),))
        filas = cur.fetchall()
        total = sum(float(f["total"]) for f in filas)
        return {"ruc": ruc.strip(), "cantidad": len(filas), "total": round(total, 2), "ventas": filas}


# ---------------------------------------------------------------------------
# Asientos de apertura
# ---------------------------------------------------------------------------
@app.get("/api/asientos-iniciales")
def listar_asientos_iniciales(actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM asientos_iniciales ORDER BY fecha, creado_en")
        asientos = cur.fetchall()
        for a in asientos:
            cur.execute("SELECT cuenta, nombre, naturaleza, debe, haber FROM asientos_iniciales_lineas WHERE asiento_id = %s ORDER BY id", (a["id"],))
            a["lineas"] = cur.fetchall()
        return asientos


@app.post("/api/asientos-iniciales")
def crear_asiento_inicial(a: AsientoInicial, actual=Depends(usuario_actual)):
    a.validar_cuadre()
    nuevo_id = a.id or str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asientos_iniciales (id, fecha, glosa) VALUES (%s,%s,%s)",
            (nuevo_id, a.fecha, a.glosa),
        )
        for linea in a.lineas:
            cur.execute(
                """INSERT INTO asientos_iniciales_lineas (asiento_id, cuenta, nombre, naturaleza, debe, haber)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (nuevo_id, linea.cuenta, linea.nombre, linea.naturaleza, linea.debe, linea.haber),
            )
        conn.commit()
        return {"id": nuevo_id, "fecha": a.fecha, "glosa": a.glosa, "lineas": [l.dict() for l in a.lineas]}


@app.delete("/api/asientos-iniciales/{asiento_id}")
def eliminar_asiento_inicial(asiento_id: str, actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM asientos_iniciales WHERE id = %s", (asiento_id,))
        conn.commit()
        return {"eliminado": cur.rowcount > 0}


# ---------------------------------------------------------------------------
# Planillas (registro de personal en el Libro Diario)
# ---------------------------------------------------------------------------
@app.get("/api/planillas")
def listar_planillas(actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM planillas ORDER BY fecha, creado_en")
        return cur.fetchall()


@app.post("/api/planillas")
def crear_planilla(p: Planilla, actual=Depends(usuario_actual)):
    p.validar()
    nuevo_id = p.id or str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO planillas (id, fecha, periodo, trabajador, dni, cargo, sueldo_bruto,
                                       essalud, sistema_pension, aporte_pension, renta_5ta,
                                       otros_descuentos, neto_pagar)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (nuevo_id, p.fecha, p.periodo, p.trabajador, p.dni, p.cargo, p.sueldo_bruto,
             p.essalud, p.sistema_pension, p.aporte_pension, p.renta_5ta, p.otros_descuentos, p.neto_pagar),
        )
        conn.commit()
        return cur.fetchone()


@app.delete("/api/planillas/{planilla_id}")
def eliminar_planilla(planilla_id: str, actual=Depends(usuario_actual)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM planillas WHERE id = %s", (planilla_id,))
        conn.commit()
        return {"eliminado": cur.rowcount > 0}


# ---------------------------------------------------------------------------
# Salud de la API
# ---------------------------------------------------------------------------
@app.get("/api/salud")
def salud():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        return {"estado": "ok", "base_de_datos": "conectada"}


# ---------------------------------------------------------------------------
# Frontend (index.html) servido desde el mismo servicio: así el enlace que
# compartas apunta a una sola URL y no hay que configurar CORS ni una
# segunda dirección para la API.
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)