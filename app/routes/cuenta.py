"""
Blueprint Cuenta — conexiones externas del usuario.

Disponible para aprendices e instructores: desde aquí vinculan su cuenta de
Google para que los avisos del sistema salgan a su nombre.
"""
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort)
from flask_login import current_user, login_required
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app import db
from app.models.cuenta_google import CuentaGoogle
from app.servicios import google_oauth
from app.utils import role_required

bp = Blueprint('cuenta', __name__, url_prefix='/cuenta')

VIGENCIA_STATE = 600  # segundos


def _serializador():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'],
                                  salt='oauth-google')


def _redirect_uri():
    """URI de retorno. Debe coincidir EXACTAMENTE con la registrada en Google."""
    from flask import current_app
    configurada = current_app.config.get('GOOGLE_REDIRECT_URI')
    return configurada or url_for('cuenta.google_callback', _external=True)


# ─── Panel de conexiones ──────────────────────
@bp.route('/conexiones')
@login_required
@role_required('aprendiz', 'instructor', 'superusuario')
def conexiones():
    return render_template(
        'cuenta/conexiones.html',
        cuenta=current_user.cuenta_google,
        google_configurado=google_oauth.esta_configurado(),
        redirect_uri=_redirect_uri(),
    )


# ─── Iniciar la autorización ──────────────────
@bp.route('/google/conectar')
@login_required
@role_required('aprendiz', 'instructor', 'superusuario')
def google_conectar():
    if not google_oauth.esta_configurado():
        flash('El administrador aún no ha configurado las credenciales de Google.',
              'warning')
        return redirect(url_for('cuenta.conexiones'))

    # El state va firmado y lleva el id del usuario: evita que la respuesta de
    # Google se acepte en una sesión distinta de la que inició el flujo.
    state = _serializador().dumps({'uid': current_user.id_usuario})
    session['oauth_google_state'] = state
    return redirect(google_oauth.url_autorizacion(_redirect_uri(), state))


# ─── Retorno de Google ────────────────────────
@bp.route('/google/callback')
@login_required
def google_callback():
    error = request.args.get('error')
    if error:
        flash('Cancelaste la conexión con Google.' if error == 'access_denied'
              else f'Google devolvió un error: {error}', 'warning')
        return redirect(url_for('cuenta.conexiones'))

    state = request.args.get('state', '')
    if not state or state != session.pop('oauth_google_state', None):
        abort(400)
    try:
        datos_state = _serializador().loads(state, max_age=VIGENCIA_STATE)
    except SignatureExpired:
        flash('La solicitud caducó. Vuelve a intentarlo.', 'warning')
        return redirect(url_for('cuenta.conexiones'))
    except BadSignature:
        abort(400)

    if datos_state.get('uid') != current_user.id_usuario:
        abort(400)

    codigo = request.args.get('code')
    if not codigo:
        flash('Google no devolvió el código de autorización.', 'danger')
        return redirect(url_for('cuenta.conexiones'))

    try:
        resultado = google_oauth.canjear_codigo(codigo, _redirect_uri())
    except google_oauth.ErrorGoogle as e:
        flash(str(e), 'danger')
        return redirect(url_for('cuenta.conexiones'))

    cuenta = current_user.cuenta_google or CuentaGoogle(id_usuario=current_user.id_usuario)
    cuenta.correo_google = resultado['correo'] or current_user.correo
    cuenta.refresh_token = google_oauth.cifrar(resultado['refresh_token'])
    cuenta.scopes = resultado['scopes']
    cuenta.fecha_conexion = datetime.now(timezone.utc)
    cuenta.ultimo_error = None
    db.session.add(cuenta)
    db.session.commit()

    flash(f'Cuenta de Google conectada: {cuenta.correo_google}', 'success')
    return redirect(url_for('cuenta.conexiones'))


# ─── Desconectar ──────────────────────────────
@bp.route('/google/desconectar', methods=['POST'])
@login_required
@role_required('aprendiz', 'instructor', 'superusuario')
def google_desconectar():
    cuenta = current_user.cuenta_google
    if not cuenta:
        return redirect(url_for('cuenta.conexiones'))

    google_oauth.revocar(cuenta.refresh_token)
    db.session.delete(cuenta)
    db.session.commit()
    flash('Cuenta de Google desconectada. Tus avisos volverán a salir desde la '
          'cuenta institucional.', 'info')
    return redirect(url_for('cuenta.conexiones'))
