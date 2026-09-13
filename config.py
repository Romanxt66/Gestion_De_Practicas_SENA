import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_secret_key():
    """Obtiene la SECRET_KEY de forma ESTABLE entre reinicios.

    Antes se generaba una clave nueva en cada arranque, lo que invalidaba todas
    las sesiones al reiniciar el proceso (y rompía el login con varios workers).
    Orden de preferencia:
      1. Variable de entorno SECRET_KEY (lo recomendado en producción).
      2. Clave persistida en instance/.secret_key (se genera la primera vez).
      3. Clave aleatoria en memoria (último recurso, si no se puede escribir).
    """
    clave = os.getenv('SECRET_KEY')
    if clave:
        return clave

    ruta = os.path.join(BASE_DIR, 'instance', '.secret_key')
    try:
        if os.path.exists(ruta):
            with open(ruta, 'r', encoding='utf-8') as f:
                guardada = f.read().strip()
            if guardada:
                return guardada
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nueva = secrets.token_urlsafe(48)
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(nueva)
        os.chmod(ruta, 0o600)
        print("SECRET_KEY generada y guardada en instance/.secret_key", flush=True)
        return nueva
    except OSError as e:
        print(f"ADVERTENCIA: no se pudo persistir SECRET_KEY ({e}). "
              "Las sesiones se invalidarán en cada reinicio. "
              "Define SECRET_KEY en el archivo .env.", flush=True)
        return secrets.token_urlsafe(48)


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError(
            "Falta la variable de entorno DATABASE_URL. "
            "Definila en el archivo .env (ver .env.example). "
            "Ejemplo para desarrollo local: "
            "DATABASE_URL=sqlite:///instance/flaskdb.sqlite"
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Reconecta conexiones caídas (Postgres cierra las inactivas) y evita
    # el error "server closed the connection unexpectedly".
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 280}

    SECRET_KEY = _get_secret_key()

    # ─── Sesión / cookies ───────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Activar solo cuando el sitio se sirve por HTTPS (en Coolify: SESSION_COOKIE_SECURE=True)
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False') == 'True'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv('SESSION_HOURS', 8)))

    # ─── Zona horaria ───────────────────────────────────
    # Los datetime se guardan en UTC, pero las fechas de práctica son fechas
    # civiles: "hoy" debe evaluarse en la hora local, no en UTC, o el progreso
    # avanzaría un día antes de tiempo cada tarde.
    APP_TIMEZONE = os.getenv('APP_TIMEZONE', 'America/Bogota')

    # ─── Subida de archivos ─────────────────────────────
    # Tamaño máximo por petición (evita que un archivo enorme tumbe el servidor)
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', 15)) * 1024 * 1024

    # ─── Configuración de correo SMTP (Gmail) ───────────
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'False') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_TIMEOUT = int(os.getenv('MAIL_TIMEOUT', 10))

    # ─── Vinculación de cuentas de Google (OAuth) ───────
    # Credenciales del proyecto en Google Cloud. Sin ellas, el apartado de
    # conexiones queda visible pero deshabilitado y todo se envía por SMTP.
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
    # Debe coincidir EXACTAMENTE con la URI registrada en Google Cloud.
    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', '')
    # Clave para cifrar los refresh tokens. Si se deja vacía se deriva de
    # SECRET_KEY, pero entonces cambiar SECRET_KEY obliga a reconectar.
    TOKEN_ENCRYPTION_KEY = os.getenv('TOKEN_ENCRYPTION_KEY', '')

# Comandos para descargar en instalar todas las librerias offline
# python -m pip download -r requirements.txt -d librerias
# pip install --no-index --find-links=librerias -r requirements.txt
