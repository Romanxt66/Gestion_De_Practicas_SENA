"""
Vinculación de cuentas de Google y envío a través de la API de Gmail.

Flujo: el usuario autoriza → Google devuelve un `code` → se canjea por un
`refresh_token` de larga duración, que se guarda cifrado. El `access_token`
dura una hora y se pide cuando hace falta, así que no se persiste.

Solo se usa la librería estándar: nada de SDKs de Google, para no arrastrar
dependencias pesadas por tres peticiones HTTP.
"""
import base64
import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

from flask import current_app

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
GMAIL_SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

# gmail.send solo permite enviar; no da acceso de lectura al buzón.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
]

TIEMPO_LIMITE = 15


class ErrorGoogle(Exception):
    """Fallo al hablar con Google, con un mensaje apto para mostrar al usuario."""


# ─────────────────────────────────────────────
# Cifrado del refresh token
# ─────────────────────────────────────────────
def _clave_cifrado():
    """Clave Fernet derivada de TOKEN_ENCRYPTION_KEY o, si falta, de SECRET_KEY.

    Ojo: si se deriva de SECRET_KEY y esta cambia, los tokens guardados dejan de
    poder descifrarse y los usuarios tendrán que volver a conectar su cuenta.
    """
    import hashlib
    from cryptography.fernet import Fernet

    explicita = current_app.config.get('TOKEN_ENCRYPTION_KEY')
    if explicita:
        material = explicita.encode('utf-8')
    else:
        material = current_app.config['SECRET_KEY'].encode('utf-8')
    derivada = hashlib.sha256(b'cuenta-google:' + material).digest()
    return Fernet(base64.urlsafe_b64encode(derivada))


def cifrar(texto: str) -> str:
    return _clave_cifrado().encrypt(texto.encode('utf-8')).decode('ascii')


def descifrar(texto: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _clave_cifrado().decrypt(texto.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError, TypeError) as e:
        raise ErrorGoogle(
            'No se pudo leer el token guardado. Vuelve a conectar tu cuenta de Google.'
        ) from e


# ─────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────
def esta_configurado() -> bool:
    """True si el servidor tiene credenciales de Google cargadas."""
    return bool(current_app.config.get('GOOGLE_CLIENT_ID')
                and current_app.config.get('GOOGLE_CLIENT_SECRET'))


def _peticion(url, datos=None, cabeceras=None, metodo=None):
    cuerpo = None
    if datos is not None:
        if isinstance(datos, dict):
            cuerpo = urllib.parse.urlencode(datos).encode('utf-8')
        else:
            cuerpo = datos
    req = urllib.request.Request(url, data=cuerpo, method=metodo,
                                 headers=cabeceras or {})
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO_LIMITE) as resp:
            return json.loads(resp.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        detalle = ''
        try:
            cuerpo_error = json.loads(e.read().decode('utf-8'))
            detalle = (cuerpo_error.get('error_description')
                       or cuerpo_error.get('error', {}).get('message')
                       or cuerpo_error.get('error') or '')
            if isinstance(detalle, dict):
                detalle = detalle.get('message', '')
        except Exception:
            pass
        raise ErrorGoogle(f'Google respondió {e.code}. {detalle}'.strip()) from e
    except urllib.error.URLError as e:
        raise ErrorGoogle(f'No se pudo contactar con Google: {e.reason}') from e


# ─────────────────────────────────────────────
# Flujo de autorización
# ─────────────────────────────────────────────
def url_autorizacion(redirect_uri: str, state: str) -> str:
    parametros = {
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        # offline + consent: imprescindible para recibir refresh_token. Sin
        # prompt=consent Google lo omite si el usuario ya autorizó antes.
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
        'state': state,
    }
    return f'{AUTH_URL}?{urllib.parse.urlencode(parametros)}'


def canjear_codigo(codigo: str, redirect_uri: str) -> dict:
    """Canjea el código por tokens. Devuelve dict con refresh_token y correo."""
    datos = _peticion(TOKEN_URL, {
        'code': codigo,
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    })

    refresh = datos.get('refresh_token')
    if not refresh:
        raise ErrorGoogle(
            'Google no entregó un token de larga duración. Revoca el acceso en '
            'tu cuenta (myaccount.google.com/permissions) e inténtalo de nuevo.'
        )

    acceso = datos.get('access_token', '')
    correo = ''
    if acceso:
        try:
            info = _peticion(USERINFO_URL, cabeceras={'Authorization': f'Bearer {acceso}'})
            correo = info.get('email', '')
        except ErrorGoogle:
            pass

    return {
        'refresh_token': refresh,
        'correo': correo,
        'scopes': datos.get('scope', ''),
    }


def access_token(refresh_token_cifrado: str) -> str:
    """Pide un access token nuevo a partir del refresh token guardado."""
    datos = _peticion(TOKEN_URL, {
        'refresh_token': descifrar(refresh_token_cifrado),
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
        'grant_type': 'refresh_token',
    })
    token = datos.get('access_token')
    if not token:
        raise ErrorGoogle('Google no devolvió un token de acceso.')
    return token


def revocar(refresh_token_cifrado: str) -> None:
    """Retira el permiso en Google. Si falla, no es crítico: igual se borra local."""
    try:
        _peticion('https://oauth2.googleapis.com/revoke',
                  {'token': descifrar(refresh_token_cifrado)})
    except ErrorGoogle:
        pass


# ─────────────────────────────────────────────
# Envío
# ─────────────────────────────────────────────
def enviar_gmail(refresh_token_cifrado: str, remitente: str, destinatario: str,
                 asunto: str, texto: str, html: str = None) -> None:
    """Envía un correo con la API de Gmail en nombre de la cuenta vinculada."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg['Subject'] = asunto
    msg['From'] = remitente
    msg['To'] = destinatario
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype='html')

    crudo = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
    token = access_token(refresh_token_cifrado)
    _peticion(
        GMAIL_SEND_URL,
        datos=json.dumps({'raw': crudo}).encode('utf-8'),
        cabeceras={'Authorization': f'Bearer {token}',
                   'Content-Type': 'application/json'},
    )
