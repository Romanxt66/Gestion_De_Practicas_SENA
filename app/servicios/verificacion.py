"""Alta de cuentas en dos pasos: primero se confirma el correo, luego existe.

Por qué no se crea el usuario y ya:
  · Una dirección con una errata dejaría una cuenta que nadie puede usar, pero
    que sí ocupa ese correo y ese número de documento para siempre.
  · El aviso de evidencia calificada iría a un buzón que no existe.

Mientras el correo no se confirma los datos viven en `verificacion_correo`.
El enlace no guarda nada en la base: lleva el identificador firmado con la
clave de la aplicación, así que no se puede fabricar ni reutilizar caducado.
"""
import json
from datetime import datetime, timedelta, timezone

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models.verificacion_correo import VerificacionCorreo
from app.servicios import correo as servicio_correo

SAL = 'verificacion-correo'
HORAS_VALIDEZ = 48


class ErrorVerificacion(Exception):
    """El enlace no sirve: caducado, manipulado o ya usado."""


def _serializador():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=SAL)


# ─────────────────────────────────────────────
# Crear y reenviar
# ─────────────────────────────────────────────
def crear_pendiente(correo, datos, origen='registro', id_creador=None):
    """Guarda el alta en espera. Si ya había una para ese correo, la sustituye."""
    correo = (correo or '').strip().lower()
    VerificacionCorreo.query.filter_by(correo=correo).delete(synchronize_session=False)
    pendiente = VerificacionCorreo(correo=correo,
                                   datos=json.dumps(datos, default=str),
                                   origen=origen,
                                   id_creador=id_creador)
    db.session.add(pendiente)
    db.session.commit()
    return pendiente


def enlace(pendiente):
    token = _serializador().dumps(pendiente.id_verificacion)
    return url_for('auth.verificar_correo', token=token, _external=True)


def enviar(pendiente, nombre=None, quien_invita=None):
    """Manda el correo de confirmación. Devuelve True si salió.

    A diferencia de los avisos del sistema, este se envía en el momento y no en
    segundo plano: si falla, hay que poder decírselo a la persona en vez de
    dejarla esperando un correo que nunca va a llegar.
    """
    nombre = nombre or 'Hola'
    url = enlace(pendiente)

    if quien_invita:
        entrada = (f'<b>{quien_invita}</b> te creó una cuenta en el Sistema de '
                   'Gestión de Prácticas del SENA. Para activarla, confirma que '
                   'esta dirección es tuya:')
        asunto = 'Activa tu cuenta — SENA Prácticas'
    else:
        entrada = ('Recibimos tu registro en el Sistema de Gestión de Prácticas '
                   'del SENA. Para terminar, confirma que esta dirección es tuya:')
        asunto = 'Confirma tu correo — SENA Prácticas'

    texto = (f'{nombre},\n\n{_sin_html(entrada)}\n\n{url}\n\n'
             f'El enlace caduca en {HORAS_VALIDEZ} horas. '
             'Si no esperabas este correo, ignóralo: sin confirmar no se crea ninguna cuenta.')

    html = servicio_correo.maqueta(
        'Confirma tu correo',
        f'<p style="margin:0 0 14px;">{nombre},</p>'
        f'<p style="margin:0 0 18px;">{entrada}</p>'
        f'<p style="margin:0 0 20px;">'
        f'<a href="{url}" style="display:inline-block;padding:12px 22px;'
        f'border-radius:10px;background:#10b981;color:#07090b;font-weight:700;'
        f'text-decoration:none;">Confirmar mi correo</a></p>'
        f'<p style="margin:0 0 6px;font-size:12px;">Si el botón no funciona, '
        f'copia esta dirección en tu navegador:</p>'
        f'<p style="margin:0;font-size:12px;word-break:break-all;color:#71717a;">{url}</p>',
        pie=(f'El enlace caduca en {HORAS_VALIDEZ} horas. Si no esperabas este '
             'correo, ignóralo: sin confirmar no se crea ninguna cuenta.'))

    return servicio_correo.enviar_ahora(pendiente.correo, asunto, texto, html)


def _sin_html(cadena):
    return cadena.replace('<b>', '').replace('</b>', '')


# ─────────────────────────────────────────────
# Confirmar
# ─────────────────────────────────────────────
def leer_token(token):
    """Devuelve el alta pendiente del enlace, o lanza ErrorVerificacion."""
    try:
        id_pendiente = _serializador().loads(token, max_age=HORAS_VALIDEZ * 3600)
    except SignatureExpired:
        raise ErrorVerificacion(
            f'El enlace caducó: solo es válido durante {HORAS_VALIDEZ} horas.')
    except BadSignature:
        raise ErrorVerificacion('El enlace no es válido.')

    pendiente = db.session.get(VerificacionCorreo, id_pendiente)
    if not pendiente:
        raise ErrorVerificacion(
            'Este enlace ya se usó o la solicitud fue cancelada.')
    return pendiente


def datos_de(pendiente):
    return json.loads(pendiente.datos)


def caducadas():
    """Altas pendientes que ya pasaron su ventana de validez."""
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_VALIDEZ)
    return [p for p in VerificacionCorreo.query.all()
            if p.fecha_creacion and _aware(p.fecha_creacion) < limite]


def _aware(fecha):
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def limpiar_caducadas():
    """Borra las que ya no sirven. Se llama al listar, no hace falta un cron."""
    borradas = 0
    for p in caducadas():
        db.session.delete(p)
        borradas += 1
    if borradas:
        db.session.commit()
    return borradas


def confirmar(pendiente):
    """Crea la cuenta de verdad a partir del alta pendiente.

    Devuelve (usuario, ficha_en_espera). `ficha_en_espera` trae el código
    cuando el aprendiz quedó sin matricular porque su ficha aún no existe.
    """
    from werkzeug.security import generate_password_hash  # noqa: F401  (ya viene cifrada)
    from app.models.aprendiz import Aprendiz
    from app.models.curso import Curso
    from app.models.curso_aprendiz import CursoAprendiz
    from app.models.instructor import Instructor
    from app.models.rol import Rol
    from app.models.usuario import Usuario
    from app.models.usuario_rol import UsuarioRol
    from app.utils import avisar_admins_ficha_pendiente, HORAS_PRACTICA_POR_DEFECTO

    d = datos_de(pendiente)
    correo = pendiente.correo

    # Entre la solicitud y la confirmación pudo pasar cualquier cosa
    if Usuario.query.filter_by(correo=correo).first():
        db.session.delete(pendiente)
        db.session.commit()
        raise ErrorVerificacion(
            'Ya existe una cuenta con ese correo. Inicia sesión con ella.')

    documento = d.get('numero_documento')
    if documento and Usuario.query.filter_by(numero_documento=documento).first():
        raise ErrorVerificacion(
            'Ya existe una cuenta con ese número de documento. '
            'Habla con un administrador.')

    usuario = Usuario(
        tipo_documento=d.get('tipo_documento') or None,
        numero_documento=documento or None,
        nombres=d['nombres'],
        apellidos=d['apellidos'],
        correo=correo,
        telefono=d.get('telefono') or None,
        password_hash=d['password_hash'],
        estado=True,
    )
    db.session.add(usuario)
    db.session.flush()

    ficha_en_espera = None
    nombre_rol = d.get('rol')

    if nombre_rol:
        rol = Rol.query.filter_by(nombre=nombre_rol).first()
        if rol:
            db.session.add(UsuarioRol(id_usuario=usuario.id_usuario,
                                      id_rol=rol.id_rol))

        if nombre_rol == 'aprendiz':
            aprendiz = Aprendiz(
                id_usuario=usuario.id_usuario,
                ficha=d.get('codigo_ficha'),
                estado_practica=d.get('estado_practica') or 'En proceso',
                horas_requeridas=d.get('horas_requeridas', HORAS_PRACTICA_POR_DEFECTO),
                horas_cumplidas=0,
                fecha_inicio_practica=_fecha(d.get('fecha_inicio_practica')),
                fecha_fin_practica=_fecha(d.get('fecha_fin_practica')),
            )
            db.session.add(aprendiz)
            db.session.flush()

            curso = Curso.query.filter_by(ficha=d.get('codigo_ficha')).first()
            if curso:
                db.session.add(CursoAprendiz(id_curso=curso.id_curso,
                                             id_aprendiz=aprendiz.id_aprendiz))
            else:
                avisar_admins_ficha_pendiente(d.get('codigo_ficha'), usuario)
                ficha_en_espera = d.get('codigo_ficha')

        elif nombre_rol == 'instructor':
            db.session.add(Instructor(id_usuario=usuario.id_usuario,
                                      area_formacion=d.get('area_formacion') or None,
                                      activo=True))

    db.session.delete(pendiente)
    db.session.commit()
    return usuario, ficha_en_espera


def _fecha(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None
