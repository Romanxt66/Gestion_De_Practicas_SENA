# Guía de despliegue y mantenimiento

## ⚠️ Lo primero: esta versión requiere un archivo `.env`

Antes se tomaba `DATABASE_URL` de `docker-compose.yml`, donde la contraseña de
Postgres estaba escrita en claro. Ahora todas las credenciales viven en `.env`
(que **no** se sube al repositorio) y el compose las lee con `env_file`.

Las variables están **declaradas** en `docker-compose.yml` como `${VARIABLE}`,
sin valor. Gracias a eso, Coolify (y cualquier panel que lea el compose) crea
los campos vacíos en su sección *Environment Variables* y solo hay que
rellenarlos desde la interfaz. Los valores reales nunca se escriben en el
compose, que va al repositorio.

**En Coolify:** recurso de la aplicación → *Environment Variables* → completar
los campos que aparecen.

**Sin panel, con `docker compose` a mano:** crear un `.env` **junto al
`docker-compose.yml`** (Compose lo lee solo para sustituir las `${...}`):

```bash
cp .env.example .env
```

> Cuidado: no basta con tener un `.env` en cualquier carpeta del servidor.
> Compose solo lee el que está junto al `docker-compose.yml`, y la aplicación
> ya no monta el proyecto dentro del contenedor.

Valores mínimos:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://admin:LA_CONTRASENA@postgres-db:5432/master_db` |

> El prefijo debe ser `postgresql+psycopg://`. Si se copia la cadena que muestra
> el panel de Postgres, vendrá como `postgres://` y SQLAlchemy no encontrará el
> driver. El host es el nombre interno del servicio (`postgres-db`), no
> `localhost`.
| `SECRET_KEY` | generar con `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SESSION_COOKIE_SECURE` | `True` si el sitio se sirve por HTTPS |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | credenciales del superusuario del seed |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | cuenta SMTP que envía las notificaciones |
| `APP_TIMEZONE` | `America/Bogota` (zona en la que se evalúa "hoy") |

> Si no defines `SECRET_KEY`, la aplicación genera una y la guarda en
> `instance/.secret_key`. Funciona, pero en un contenedor sin volumen
> persistente esa carpeta se pierde en cada redeploy y las sesiones se cierran.
> **Lo recomendado es definir `SECRET_KEY` en el `.env`.**

## Primer despliegue de esta versión

1. Crear el `.env` como se indicó arriba.
2. Reconstruir la imagen (cambió `requirements.txt`, que además estaba en UTF‑16
   y por eso `pip install -r` fallaba):

   ```bash
   docker compose up -d --build
   ```

3. **Marcar la base de datos existente como ya migrada.** El proyecto ahora usa
   Flask‑Migrate. Como las tablas ya existen en producción, hay que sellar el
   estado en lugar de volver a crearlas:

   ```bash
   docker compose exec web flask db stamp b2dfee22bcd7
   ```

   Este paso se hace **una sola vez**. Si se omite, el primer
   `flask db upgrade` intentará crear tablas que ya existen y fallará.

   > ⚠️ Sellar con `head` en lugar de `b2dfee22bcd7` es un error: `head` apunta
   > siempre a la **última** migración, así que Alembic daría por aplicadas
   > migraciones que la base todavía no tiene y esas columnas nunca se crearían.
   > Hay que sellar la revisión que refleja el esquema real de producción, que
   > es la inicial (`b2dfee22bcd7`).

4. **Aplicar las migraciones pendientes:**

   ```bash
   docker compose exec web flask db upgrade
   ```

   Agrega `fecha_inicio_practica` y `fecha_fin_practica` a la tabla `aprendiz`.
   Para confirmar en qué revisión quedó la base:

   ```bash
   docker compose exec web flask db current
   ```

5. Verificar que el sitio responde y que se puede iniciar sesión.

> Al desplegar, **todas las sesiones activas se cierran** (cambia la clave de
> firma). Es normal: los usuarios solo tienen que volver a entrar.

## Cambios de esquema de aquí en adelante

Nunca vuelvas a confiar en `db.create_all()` para modificar tablas: solo crea
las que faltan, jamás altera una existente. El flujo correcto es:

```bash
# 1. Editar el modelo en app/models/
# 2. Generar la migración (en local)
flask db migrate -m "descripción del cambio"
# 3. Revisar a mano el archivo generado en migrations/versions/
# 4. Aplicarla
flask db upgrade
```

En producción, tras desplegar el código nuevo:

```bash
docker compose exec web flask db upgrade
```

> **Pendiente en el próximo despliegue:** la migración `d6c632069ed4` agrega
> `fecha_inicio_practica` y `fecha_fin_practica` a la tabla `aprendiz`. Son dos
> columnas nulables, así que el `ALTER TABLE` es instantáneo y no bloquea; los
> aprendices existentes quedan sin fechas y siguen con la estimación de 6 meses
> hasta que un instructor las cargue.

Con varios workers conviene además poner `RUN_DB_INIT=0` en el `.env` para que
el arranque no ejecute `create_all()`/seed en paralelo.

## Desarrollo local

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # y poner DATABASE_URL=sqlite:///flaskdb.sqlite
.venv/bin/python run.py   # http://localhost:5001
```

Para activar el recargado automático y el depurador: `FLASK_DEBUG=1`.
(Antes el `debug=True` estaba fijo en el código, lo que también quedaba
activo en producción.)

## Nota sobre el servidor

`run.py` levanta el servidor de desarrollo de Werkzeug, que no está pensado
para producción. Cuando quieras dar el paso, agregá `gunicorn` a
`requirements.txt` y cambiá el `CMD` del `Dockerfile` por:

```
CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:5001", "run:app"]
```

Con varios workers, `SECRET_KEY` en el `.env` y `RUN_DB_INIT=0` dejan de ser
recomendaciones y pasan a ser obligatorios.

## Archivos de evidencia

Se guardan en `app/static/uploads/evidencias/`. El acceso directo por
`/static/uploads/...` está bloqueado; se descargan por
`/archivos/evidencia/<id>`, que valida que quien pide el archivo sea el
aprendiz dueño, un instructor de su ficha o un superusuario.

Se conservan en el volumen `evidencias`, declarado en `docker-compose.yml`.

> **Importante:** el compose **no** debe montar el proyecto sobre `/app`
> (`- .:/app`). Ese montaje tapa el código recién construido y el contenedor
> sigue ejecutando la versión anterior, aunque el despliegue aparezca en verde.
> El código viaja dentro de la imagen (`COPY . .` en el Dockerfile); en
> volúmenes va solo lo que debe sobrevivir al redespliegue: las evidencias
> subidas y la carpeta `instance` (donde se persiste la clave de sesión).

Para copiar evidencias que estuvieran en una carpeta del servidor al volumen:

```bash
CONT=$(docker ps --format '{{.Names}}' | grep '^web-' | head -1)
docker cp <ruta-en-el-servidor>/app/static/uploads/evidencias/. \
          $CONT:/app/app/static/uploads/evidencias/
```


## Vincular cuentas de Google (apartado "Conexiones")

Aprendices e instructores pueden vincular su cuenta de Google para que los
avisos del sistema salgan desde su propia dirección. **Es opcional**: sin
vincular nada, los avisos se envían desde la cuenta institucional
(`MAIL_USERNAME`), así que la funcionalidad nunca depende de ello.

Avisos que se envían:

| Cuándo | A quién |
|---|---|
| Un aprendiz sube una evidencia | Al instructor de cada ficha del aprendiz |
| Un instructor califica una evidencia | Al aprendiz |

### Configuración en Google Cloud

1. En [console.cloud.google.com](https://console.cloud.google.com) → *APIs y
   servicios* → habilitar la **Gmail API**.
2. *Credenciales* → crear un **ID de cliente de OAuth** de tipo *Aplicación web*.
3. En **URIs de redireccionamiento autorizados**, añadir exactamente:
   `https://TU-DOMINIO/cuenta/google/callback`
4. Copiar el ID y el secreto a las variables `GOOGLE_CLIENT_ID` y
   `GOOGLE_CLIENT_SECRET`, y poner esa misma URI en `GOOGLE_REDIRECT_URI`.

> ⚠️ **Límite mientras la app no esté verificada por Google.** El permiso que se
> pide (`gmail.send`) es sensible. Con la pantalla de consentimiento en modo
> *Prueba*, solo funcionan las cuentas añadidas a mano como usuarios de prueba
> (máximo 100) y **el permiso caduca a los 7 días**, obligando a reconectar.
> Para usarlo con una ficha entera hay que publicar la app y pasar la
> verificación de Google (requiere política de privacidad, dominio verificado y
> un vídeo de demostración; tarda semanas).
>
> Por eso el sistema **no depende de esto**: mientras tanto, basta con dejar
> `MAIL_USERNAME`/`MAIL_PASSWORD` configuradas y todos los avisos salen desde la
> cuenta institucional.

### Cifrado de los tokens

El *refresh token* que devuelve Google se guarda **cifrado** (Fernet) en la
tabla `cuenta_google`. La clave sale de `TOKEN_ENCRYPTION_KEY`; si se deja
vacía, se deriva de `SECRET_KEY` — y entonces cambiar `SECRET_KEY` deja los
tokens ilegibles y los usuarios tendrán que volver a conectar su cuenta.
Conviene definirla explícitamente:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```
