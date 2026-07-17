# Sistema Contable — Libro Mayor & Diario (con PostgreSQL)

Todo el sistema (API + interfaz web) corre desde **un solo servicio**: `app.py`.
Al abrir la URL raíz (`/`) se sirve directamente `index.html`, ya conectado a la
API bajo `/api`. Eso significa que solo hay **una dirección** que compartir, sin
configurar CORS ni dos servidores distintos.

```
sistema-contable/
├── app.py              → API (FastAPI) + sirve el frontend
├── index.html           → la interfaz web
├── schema.sql            → estructura de la base de datos PostgreSQL
├── requirements.txt
└── .env.example
```

Incluye:
- Registro de **compras** (con asiento principal + destino a existencias).
- Registro de **ventas** (con asiento principal + destino a costo de ventas 6911),
  retención del 12% en facturas, y **búsqueda de facturas emitidas por RUC**.
- **Planillas**: registra sueldos, calcula ESSALUD (9% a cargo de la empresa) y el
  descuento por ONP/AFP, y genera automáticamente el asiento de gasto de personal
  en el Libro Diario / Libro Mayor.
- Libro Diario, Libro Mayor, Hoja de Trabajo, Estado de Resultados y Estado de
  Situación Financiera, generados automáticamente.
- **Acceso con usuario y contraseña**: la primera persona que abre el sistema crea
  su propio usuario administrador; nadie puede ver ni modificar los datos sin
  iniciar sesión.

---

## 1. Correrlo en tu computadora (localhost)

### Requisitos
- Python 3.10 o superior.
- PostgreSQL (local o en la nube).
- `git` (para bajar el proyecto).

### Pasos

**a) Instalar PostgreSQL** (si no lo tienes)

- Windows: instalador desde https://www.postgresql.org/download/windows/
- Mac: `brew install postgresql@16 && brew services start postgresql@16`
- Linux: `sudo apt install postgresql postgresql-contrib && sudo systemctl start postgresql`

**b) Crear la base de datos**

```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE contable_db;
CREATE USER contable_user WITH PASSWORD 'cambia_esta_clave';
GRANT ALL PRIVILEGES ON DATABASE contable_db TO contable_user;
\q
```

**c) Clonar el proyecto y cargar las tablas**

```bash
git clone https://github.com/leotrevis838-ship-it/sistema-contable.git
cd sistema-contable
psql -U contable_user -d contable_db -h localhost -f schema.sql
```

**d) Instalar dependencias de Python**

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**e) Configurar las variables de entorno**

```bash
cp .env.example .env
```
Edita `.env`:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=contable_db
DB_USER=contable_user
DB_PASSWORD=cambia_esta_clave
```

**f) Levantar el sistema**

```bash
python app.py
```

Abre **http://localhost:8000** en tu navegador. La primera vez te pedirá crear tu
usuario y contraseña de administrador (eso se guarda en la base de datos, no en el
código, así que solo tú lo sabes).

---

## 2. Compartirlo como sitio web (con un enlace)

La forma más simple y gratuita para este tipo de proyecto es **Render**
(render.com), porque en un solo lugar puedes crear la base de datos PostgreSQL y
publicar `app.py` como servicio web. Pasos:

1. Sube el proyecto a GitHub (ya lo tienes en
   `github.com/leotrevis838-ship-it/sistema-contable`).
2. En Render: **New → PostgreSQL** → crea una base de datos gratuita. Copia el
   "Internal Database URL" o los datos de conexión (host, usuario, clave, nombre
   de base de datos, puerto) que te muestra.
3. Con `psql` (desde tu computadora, apuntando a esa base remota) carga
   `schema.sql`:
   ```bash
   psql "postgresql://usuario:clave@host:puerto/nombre_bd" -f schema.sql
   ```
4. En Render: **New → Web Service** → conecta tu repositorio de GitHub.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Variables de entorno: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
     `DB_PASSWORD` con los datos de la base creada en el paso 2.
5. Cuando termine el despliegue, Render te da una URL pública, por ejemplo
   `https://sistema-contable.onrender.com`. Esa es la única dirección que
   necesitas compartir: al abrirla, la persona crea su propio usuario y
   contraseña de administrador, y a partir de ahí queda protegida con ese login.

Alternativas equivalentes: Railway (railway.app) y Fly.io funcionan igual de bien
y también ofrecen PostgreSQL gestionado; los pasos son prácticamente los mismos
(build command, start command y variables de entorno de la base de datos).

> El plan gratuito de Render "duerme" el servicio si nadie lo usa por un rato — la
> primera visita después de un tiempo tarda unos segundos en despertar, es normal.

---

## Notas sobre los cálculos

- **Retención del 12%** (ventas): se calcula sobre el total del comprobante
  (base + IGV), solo en comprobantes tipo Factura.
- **Costo de ventas**: al registrar una venta con "costo" mayor a 0, se genera un
  segundo asiento (destino) que carga 6911 - Costo de Ventas y descarga 2011 -
  Mercaderías.
- **Compras**: cada compra genera su asiento principal (IGV + cuenta por pagar) y
  su asiento de destino a existencias (2011).
- **Planillas**: ESSALUD se calcula automáticamente como 9% del sueldo bruto
  (gasto de la empresa, no se descuenta al trabajador). El aporte a pensión
  (ONP 13% referencial, o el monto que definas para AFP) sí se descuenta del
  neto a pagar. Puedes editar manualmente el monto de pensión, la retención de
  Renta de 5.ª categoría y otros descuentos antes de guardar la boleta. El asiento
  generado carga 6211 (Sueldos) y 6271 (ESSALUD), y abona 4111 (Remuneraciones por
  pagar), 4032/4033 (ONP/AFP por pagar), 40171 (Renta 5.ª por pagar) y 4031
  (ESSALUD por pagar) — siempre cuadrado en Debe = Haber.
- Si alguna tasa (ONP, AFP, retención) es distinta en tu caso, son valores
  editables en el propio formulario antes de registrar.

## Problemas comunes

- **"Sin conexión al backend"** en la página → confirma que `python app.py` (o el
  servicio en Render) esté corriendo y que `.env` tenga los datos correctos.
- **401 / "Sesión inválida o expirada"** → vuelve a iniciar sesión con el botón
  "Cerrar sesión" y luego ingresa de nuevo tu usuario y contraseña.
- **Olvidé la contraseña de administrador** → como es un solo usuario por
  instalación, entra directamente a la base de datos y borra la fila de la tabla
  `usuarios` (`DELETE FROM usuarios;`); la próxima vez que abras el sistema te
  pedirá crear un administrador nuevo.
