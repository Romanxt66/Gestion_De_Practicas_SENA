import logging
import os

from flask import Flask, render_template, request, abort
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()


def create_app():

    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Detrás del proxy de Coolify/Traefik, la app recibe la petición por HTTP y
    # sin ProxyFix creería que el sitio es http://, generando enlaces externos
    # incorrectos (por ejemplo la URI de retorno de Google). Los encabezados
    # X-Forwarded-* los pone el proxy; el contenedor no se expone directamente.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Inicia sesión para continuar.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(id_usuario):
        from .models.usuario import Usuario
        return db.session.get(Usuario, int(id_usuario))

    # Importar modelos para que SQLAlchemy (y Alembic) los registre
    with app.app_context():
        from app.models import (
            usuario, rol, usuario_rol, instructor,
            aprendiz, curso, curso_instructor, curso_aprendiz,
            evidencia, progreso_aprendiz, empresa,
            historial_cambios, notificacion, aprendiz_backup,
            cuenta_google, verificacion_correo, instructor_aprendiz
        )

    # Register blueprints
    from app.routes import auth, instructor, aprendiz, admin, archivos, cuenta
    app.register_blueprint(auth.bp)
    app.register_blueprint(instructor.bp)
    app.register_blueprint(aprendiz.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(archivos.bp)
    app.register_blueprint(cuenta.bp)

    # ─────────────────────────────────────────────
    # Las evidencias viven en static/uploads/ pero NO deben ser públicas:
    # se sirven únicamente por /archivos/evidencias/<nombre>, que valida permisos.
    # ─────────────────────────────────────────────
    @app.before_request
    def bloquear_acceso_directo_a_uploads():
        if request.path.startswith('/static/uploads/'):
            abort(404)

    # ─────────────────────────────────────────────
    # Manejo de errores
    # ─────────────────────────────────────────────
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return render_template(
            'errores/error.html',
            codigo=400,
            titulo='Sesión expirada',
            mensaje='Tu sesión expiró o el formulario no es válido. '
                    'Vuelve a iniciar sesión e inténtalo de nuevo.'
        ), 400

    @app.errorhandler(403)
    def handle_403(e):
        return render_template(
            'errores/error.html',
            codigo=403,
            titulo='Acceso denegado',
            mensaje='No tienes permiso para acceder a esta sección.'
        ), 403

    @app.errorhandler(404)
    def handle_404(e):
        return render_template(
            'errores/error.html',
            codigo=404,
            titulo='Página no encontrada',
            mensaje='La página que buscas no existe o fue movida.'
        ), 404

    @app.errorhandler(413)
    def handle_413(e):
        limite = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        return render_template(
            'errores/error.html',
            codigo=413,
            titulo='Archivo demasiado grande',
            mensaje=f'El archivo supera el límite de {limite} MB permitido.'
        ), 413

    @app.errorhandler(Exception)
    def handle_error(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e  # Flask maneja los errores HTTP estándar
        # Deshacer la transacción rota para no envenenar la sesión de BD
        try:
            db.session.rollback()
        except Exception:
            pass
        # Se registra el detalle en el log, pero NUNCA se expone al usuario
        app.logger.exception("Error no controlado en %s", request.path)
        return render_template(
            'errores/error.html',
            codigo=500,
            titulo='Error interno',
            mensaje='Ocurrió un error inesperado. Si persiste, contacta al administrador.'
        ), 500

    @app.context_processor
    def inyectar_globales():
        """Valores disponibles en todas las plantillas.

        Solo datos de presentación para el armazón (año y contadores de los
        avisos de la barra superior). No altera ninguna regla de negocio.
        """
        from datetime import datetime
        from flask_login import current_user
        from app.utils import hoy_local, EVIDENCIAS_ESPERADAS, CATALOGO_EVIDENCIAS

        try:
            anio = hoy_local().year
        except Exception:
            anio = datetime.now().year

        datos = {'anio_actual': anio, 'nav_notificaciones': 0, 'nav_pendientes': 0,
                 'evidencias_esperadas': EVIDENCIAS_ESPERADAS,
                 'catalogo_evidencias': CATALOGO_EVIDENCIAS}

        try:
            if current_user.is_authenticated:
                if current_user.aprendiz:
                    from app.models.notificacion import Notificacion
                    datos['nav_notificaciones'] = Notificacion.query.filter_by(
                        id_usuario=current_user.id_usuario, leida=False).count()
                elif current_user.instructor:
                    from app.utils import (ids_aprendices_de_instructor,
                                           contar_evidencias_por_aprendiz)
                    ids = ids_aprendices_de_instructor(current_user.instructor)
                    conteos = contar_evidencias_por_aprendiz(ids, estado='Entregada')
                    datos['nav_pendientes'] = sum(conteos.values())
        except Exception:
            # Un contador nunca debe impedir que se pinte la página
            pass

        return datos

    @app.after_request
    def add_header(response):
        # Estáticos: 'no-cache' NO significa "no guardar", sino "revalida antes
        # de usar". El navegador conserva el archivo y el servidor responde 304
        # si no cambió. Es lo correcto aquí porque las URL no llevan versión:
        # con un max-age largo, un cambio de CSS tardaría semanas en llegar.
        if request.endpoint == 'static':
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    return app
