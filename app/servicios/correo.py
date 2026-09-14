"""
Envío de las notificaciones por correo del sistema.

Dos remitentes posibles, en este orden:
  1. La cuenta de Google que el propio usuario vinculó (el correo sale a su
     nombre, vía API de Gmail).
  2. La cuenta institucional configurada en MAIL_USERNAME/MAIL_PASSWORD (SMTP).

Si el usuario no ha vinculado nada, el aviso igual se envía por la cuenta
institucional: la notificación nunca depende de que alguien conecte su Google.

Todo sale en un hilo aparte para no dejar esperando a quien sube o califica.
"""
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app

from app.servicios import google_oauth


# ─────────────────────────────────────────────
# Transportes
# ─────────────────────────────────────────────
def _construir_mensaje(remitente_correo, remitente_nombre, destinatario,
                       asunto, texto, html, responder_a=None):
    """Monta el correo. Mismo mensaje para los dos transportes.

    Detalles que reducen las probabilidades de acabar en spam: un nombre
    visible en el remitente (en vez del correo pelado), una dirección de
    respuesta real, y la marca de mensaje automático de la RFC 3834, que evita
    además que un autorespondedor del destinatario conteste en bucle.
    """
    msg = EmailMessage()
    msg['Subject'] = asunto
    msg['From'] = formataddr((remitente_nombre, remitente_correo))
    msg['To'] = destinatario
    if responder_a:
        msg['Reply-To'] = responder_a
    msg['Auto-Submitted'] = 'auto-generated'
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype='html')
    return msg


def _enviar_smtp(cfg, mensaje):
    if cfg['ssl']:
        with smtplib.SMTP_SSL(cfg['servidor'], cfg['puerto'], timeout=cfg['timeout']) as s:
            s.login(cfg['usuario'], cfg['password'])
            s.send_message(mensaje)
    else:
        with smtplib.SMTP(cfg['servidor'], cfg['puerto'], timeout=cfg['timeout']) as s:
            s.starttls()
            s.login(cfg['usuario'], cfg['password'])
            s.send_message(mensaje)


def _config_smtp():
    return {
        'usuario': current_app.config.get('MAIL_USERNAME'),
        'password': current_app.config.get('MAIL_PASSWORD'),
        'servidor': current_app.config.get('MAIL_SERVER'),
        'puerto': current_app.config.get('MAIL_PORT'),
        'ssl': current_app.config.get('MAIL_USE_SSL'),
        'timeout': current_app.config.get('MAIL_TIMEOUT', 10),
    }


def _entregar(app, datos):
    """Se ejecuta en el hilo: intenta Gmail del usuario y si no, SMTP institucional."""
    with app.app_context():
        destinatario = datos['destinatario']

        if datos['refresh_token'] and google_oauth.esta_configurado():
            mensaje = _construir_mensaje(
                datos['remitente'], datos['remitente_nombre'], destinatario,
                datos['asunto'], datos['texto'], datos['html'],
                responder_a=datos['remitente'])
            try:
                google_oauth.enviar_gmail(datos['refresh_token'], mensaje)
                return
            except google_oauth.ErrorGoogle as e:
                # Se registra el motivo en la cuenta para poder avisar al usuario
                _anotar_error(datos['id_cuenta'], str(e))
                current_app.logger.warning(
                    'Gmail falló para %s (%s). Se usa la cuenta institucional.',
                    datos['remitente'], e)

        cfg = _config_smtp()
        if not cfg['usuario'] or not cfg['password']:
            current_app.logger.warning(
                'Sin MAIL_USERNAME/MAIL_PASSWORD y sin cuenta de Google: '
                'no se envió el aviso a %s.', destinatario)
            return
        # Por la cuenta institucional el remitente es el sistema, pero la
        # respuesta sigue yendo a la persona que originó el aviso.
        mensaje = _construir_mensaje(
            cfg['usuario'], 'SENA Prácticas', destinatario,
            datos['asunto'], datos['texto'], datos['html'],
            responder_a=datos['responder_a'])
        try:
            _enviar_smtp(cfg, mensaje)
        except Exception as e:
            current_app.logger.warning('No se pudo enviar el correo a %s: %s',
                                       destinatario, e)


def _anotar_error(id_cuenta, mensaje):
    if not id_cuenta:
        return
    try:
        from app import db
        from app.models.cuenta_google import CuentaGoogle
        cuenta = db.session.get(CuentaGoogle, id_cuenta)
        if cuenta:
            cuenta.ultimo_error = mensaje[:500]
            db.session.commit()
    except Exception:
        db.session.rollback()


def enviar(destinatario: str, asunto: str, texto: str, html: str = None,
           remitente_usuario=None) -> None:
    """Encola un correo. `remitente_usuario` es el Usuario que origina el aviso."""
    if not destinatario:
        return

    cuenta = getattr(remitente_usuario, 'cuenta_google', None) if remitente_usuario else None
    nombre = (f'{remitente_usuario.nombres} {remitente_usuario.apellidos}'
              if remitente_usuario else 'SENA Prácticas')
    datos = {
        'destinatario': destinatario,
        'asunto': asunto,
        'texto': texto,
        'html': html,
        'refresh_token': cuenta.refresh_token if cuenta else None,
        'remitente': cuenta.correo_google if cuenta else current_app.config.get('MAIL_USERNAME'),
        # Nombre visible: "Roman Torres (SENA Prácticas)" se reconoce mejor que
        # un correo suelto, y ayuda a que no se tome por spam.
        'remitente_nombre': f'{nombre} · SENA Prácticas' if cuenta else 'SENA Prácticas',
        'responder_a': remitente_usuario.correo if remitente_usuario else None,
        'id_cuenta': cuenta.id_cuenta if cuenta else None,
    }
    hilo = threading.Thread(target=_entregar,
                            args=(current_app._get_current_object(), datos),
                            daemon=True)
    hilo.start()


# ─────────────────────────────────────────────
# Plantilla
# ─────────────────────────────────────────────
def _maqueta(titulo: str, cuerpo_html: str, pie: str = '') -> str:
    return f"""\
<!doctype html>
<html lang="es"><body style="margin:0;background:#0a0a0a;padding:28px 16px;
 font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:520px;background:#111;
       border:1px solid rgba(255,255,255,.08);border-radius:16px;" cellpadding="0" cellspacing="0">
        <tr><td style="padding:26px 28px 0;">
          <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:#10b981;font-weight:700;">SENA Prácticas</div>
          <h1 style="margin:12px 0 0;font-size:20px;color:#fff;font-weight:700;">{titulo}</h1>
        </td></tr>
        <tr><td style="padding:16px 28px 26px;color:#a1a1aa;font-size:14px;line-height:1.6;">
          {cuerpo_html}
        </td></tr>
        {'<tr><td style="padding:0 28px 24px;color:#71717a;font-size:12px;">' + pie + '</td></tr>' if pie else ''}
      </table>
      <div style="max-width:520px;margin-top:14px;color:#52525b;font-size:11px;">
        Mensaje automático del Sistema de Gestión de Prácticas. No respondas a este correo.
      </div>
    </td></tr>
  </table>
</body></html>"""


# ─────────────────────────────────────────────
# Avisos del sistema
# ─────────────────────────────────────────────
def avisar_evidencia_subida(instructor_usuario, aprendiz_usuario, curso_nombre: str,
                            tipo_evidencia: str) -> None:
    """El aprendiz subió una evidencia → se avisa al instructor de la ficha."""
    nombre = f'{aprendiz_usuario.nombres} {aprendiz_usuario.apellidos}'
    asunto = f'Nueva evidencia de {nombre} — {curso_nombre}'
    texto = (
        f'{nombre} subió una evidencia ({tipo_evidencia}) en la ficha {curso_nombre}.\n\n'
        'Ingresa al sistema para revisarla.'
    )
    html = _maqueta(
        'Nueva evidencia por revisar',
        f'<p style="margin:0 0 10px;"><strong style="color:#fff;">{nombre}</strong> '
        f'subió una evidencia en la ficha <strong style="color:#fff;">{curso_nombre}</strong>.</p>'
        f'<p style="margin:0;">Tipo de entrega: {tipo_evidencia}.</p>',
        'Ingresa al sistema para revisarla y calificarla.')
    enviar(instructor_usuario.correo, asunto, texto, html,
           remitente_usuario=aprendiz_usuario)


def avisar_evidencia_calificada(aprendiz_usuario, instructor_usuario, estado: str,
                                observaciones: str, fecha_entrega) -> None:
    """El instructor calificó la evidencia → se avisa al aprendiz."""
    fecha = fecha_entrega.strftime('%d/%m/%Y') if fecha_entrega else ''
    asunto = f'Tu evidencia fue calificada: {estado}'
    instructor = f'{instructor_usuario.nombres} {instructor_usuario.apellidos}'

    texto = (f'Tu evidencia del {fecha} fue revisada por {instructor} '
             f'y quedó como "{estado}".')
    if observaciones:
        texto += f'\n\nObservaciones del instructor:\n{observaciones}'
    texto += '\n\nIngresa al sistema para ver el detalle.'

    color = '#10b981' if estado == 'Aprobada' else '#f59e0b'
    cuerpo = (
        f'<p style="margin:0 0 14px;">Tu evidencia del <strong style="color:#fff;">{fecha}</strong> '
        f'fue revisada por {instructor}.</p>'
        f'<p style="margin:0 0 14px;">Resultado: '
        f'<strong style="color:{color};">{estado}</strong></p>'
    )
    if observaciones:
        cuerpo += (
            '<p style="margin:0 0 6px;color:#71717a;font-size:12px;'
            'text-transform:uppercase;letter-spacing:.1em;">Observaciones</p>'
            f'<p style="margin:0;padding:12px 14px;background:rgba(255,255,255,.03);'
            f'border-left:2px solid {color};border-radius:6px;">{observaciones}</p>'
        )
    html = _maqueta('Evidencia calificada', cuerpo,
                    'Ingresa al sistema para ver el detalle de tu progreso.')
    enviar(aprendiz_usuario.correo, asunto, texto, html,
           remitente_usuario=instructor_usuario)
