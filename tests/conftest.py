"""Configuración compartida de pytest.

Las variables de entorno se fijan ANTES de importar la aplicación porque
config.Config lee DATABASE_URL una sola vez, al importarse. La base de datos es
un SQLite temporal creado desde cero (esquema + datos semilla), así que las
pruebas no dependen de instance/flaskdb.sqlite ni tocan datos reales.
"""
import os
import re
import shutil
import sys
import tempfile
import uuid
from types import SimpleNamespace

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Scripts antiguos: se ejecutan al importarse y exigen instance/flaskdb.sqlite.
collect_ignore = ['test_funcional.py', 'smoke.py']

_TMP = tempfile.mkdtemp(prefix='sena-pytest-')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_TMP, 'pruebas.sqlite')
os.environ['RUN_DB_INIT'] = '0'
os.environ['SECRET_KEY'] = 'clave-de-prueba'
# Un .env de desarrollo no debe colarse en las pruebas (load_dotenv no pisa
# lo que ya esté definido en el entorno).
for _variable in ('MAIL_USERNAME', 'MAIL_PASSWORD', 'GOOGLE_CLIENT_ID',
                  'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'TOKEN_ENCRYPTION_KEY'):
    os.environ[_variable] = ''

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models.aprendiz import Aprendiz  # noqa: E402
from app.models.curso import Curso  # noqa: E402
from app.models.curso_aprendiz import CursoAprendiz  # noqa: E402
from app.models.curso_instructor import CursoInstructor  # noqa: E402
from app.models.evidencia import Evidencia  # noqa: E402
from app.models.instructor import Instructor  # noqa: E402
from app.models.rol import Rol  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.models.usuario_rol import UsuarioRol  # noqa: E402

CLAVE_ADMIN = 'clave-admin-test'
CLAVE_INSTRUCTOR = 'clave-inst-test'
CLAVE_APRENDIZ = 'clave-ap-test'
CORREO_ADMIN = 'admin@sena.edu.co'


def unico(prefijo='x'):
    """Sufijo único para correos/documentos de usuarios desechables."""
    return f'{prefijo}{uuid.uuid4().hex[:8]}'


def crear_usuario(rol, correo=None, clave='clave123', **extra):
    """Crea un usuario desechable con su rol y perfil. Devuelve sus ids.

    Debe llamarse dentro de un `app.app_context()`.
    """
    correo = correo or f'{unico("u")}@test.local'
    usuario = Usuario(nombres=extra.pop('nombres', 'Prueba'),
                      apellidos=extra.pop('apellidos', 'Desechable'),
                      correo=correo,
                      password_hash=generate_password_hash(clave), estado=True,
                      tipo_documento=extra.pop('tipo_documento', None),
                      numero_documento=extra.pop('numero_documento', None))
    db.session.add(usuario)
    db.session.flush()
    rol_db = Rol.query.filter_by(nombre=rol).first()
    db.session.add(UsuarioRol(id_usuario=usuario.id_usuario, id_rol=rol_db.id_rol))
    ids = {'id_usuario': usuario.id_usuario, 'correo': correo}
    if rol == 'aprendiz':
        ap = Aprendiz(id_usuario=usuario.id_usuario, ficha=extra.pop('ficha', None),
                      estado_practica=extra.pop('estado_practica', 'En proceso'),
                      horas_requeridas=880, horas_cumplidas=0)
        db.session.add(ap)
        db.session.flush()
        ids['id_aprendiz'] = ap.id_aprendiz
    elif rol == 'instructor':
        ins = Instructor(id_usuario=usuario.id_usuario,
                         area_formacion=extra.pop('area_formacion', 'Sistemas'),
                         activo=True)
        db.session.add(ins)
        db.session.flush()
        ids['id_instructor'] = ins.id_instructor
    db.session.commit()
    return SimpleNamespace(**ids)


def crear_curso(nombre=None, ficha=None, **extra):
    """Ficha desechable. Debe llamarse dentro de un `app.app_context()`."""
    curso = Curso(nombre=nombre or f'Curso {unico()}', ficha=ficha or unico('F'), **extra)
    db.session.add(curso)
    db.session.commit()
    return curso.id_curso


@pytest.fixture(scope='session')
def app():
    from app.servicios import correo as serv_correo

    app = create_app()
    app.config['SERVER_NAME'] = 'localhost'
    app.config['TESTING'] = True

    # El correo nunca sale de verdad: se anota a dónde habría ido.
    app.correos = []
    original = app.enviar_ahora_real = serv_correo.enviar_ahora
    serv_correo.enviar_ahora = lambda destinatario, asunto, texto, html=None: (
        app.correos.append({'para': destinatario, 'asunto': asunto, 'texto': texto})
        or True)

    with app.app_context():
        db.create_all()
        _sembrar()

    carpeta = os.path.join(RAIZ, 'app', 'static', 'uploads', 'evidencias')
    antes = set(os.listdir(carpeta)) if os.path.isdir(carpeta) else set()

    yield app

    serv_correo.enviar_ahora = original
    if os.path.isdir(carpeta):
        for nombre in set(os.listdir(carpeta)) - antes:
            os.remove(os.path.join(carpeta, nombre))
    shutil.rmtree(_TMP, ignore_errors=True)


def _sembrar():
    """Roles, un administrador, un instructor con su ficha y dos aprendices:
    uno de esa ficha ("propio") y otro de otra ficha ("ajeno")."""
    for nombre in ('aprendiz', 'instructor', 'superusuario'):
        db.session.add(Rol(nombre=nombre, descripcion=f'Rol de {nombre}'))
    db.session.commit()

    admin = crear_usuario('aprendiz', correo=CORREO_ADMIN, clave=CLAVE_ADMIN,
                          nombres='Admin', apellidos='SENA')
    # El administrador no es aprendiz: se le cambia el rol y se borra el perfil.
    UsuarioRol.query.filter_by(id_usuario=admin.id_usuario).delete()
    Aprendiz.query.filter_by(id_usuario=admin.id_usuario).delete()
    db.session.add(UsuarioRol(id_usuario=admin.id_usuario,
                              id_rol=Rol.query.filter_by(nombre='superusuario').first().id_rol))
    db.session.commit()

    instructor = crear_usuario('instructor', correo='instructor@test.local',
                               clave=CLAVE_INSTRUCTOR, nombres='Ivana', apellidos='Instructora',
                               area_formacion='Teleinformática')
    curso1 = Curso(nombre='Análisis y Desarrollo de Software', ficha='CI0001')
    curso2 = Curso(nombre='Ficha de Otro Instructor', ficha='CI0002')
    db.session.add_all([curso1, curso2])
    db.session.flush()
    db.session.add(CursoInstructor(id_curso=curso1.id_curso,
                                   id_instructor=instructor.id_instructor))

    propio = crear_usuario('aprendiz', correo='aprendiz.propio@test.local',
                           clave=CLAVE_APRENDIZ, nombres='Paula', apellidos='Propia',
                           ficha='CI0001')
    ajeno = crear_usuario('aprendiz', correo='aprendiz.ajeno@test.local',
                          clave=CLAVE_APRENDIZ, nombres='Andres', apellidos='Ajeno',
                          ficha='CI0002')
    db.session.add(CursoAprendiz(id_curso=curso1.id_curso, id_aprendiz=propio.id_aprendiz))
    db.session.add(CursoAprendiz(id_curso=curso2.id_curso, id_aprendiz=ajeno.id_aprendiz))
    db.session.add(Evidencia(id_aprendiz=propio.id_aprendiz, tipo='archivo',
                             contenido='uploads/evidencias/inexistente.pdf',
                             estado='Entregada', documento='acta'))
    db.session.commit()


@pytest.fixture(scope='session')
def datos(app):
    """Identificadores de los datos semilla (ids, no objetos ORM)."""
    with app.app_context():
        admin = Usuario.query.filter_by(correo=CORREO_ADMIN).first()
        inst = Usuario.query.filter_by(correo='instructor@test.local').first()
        propio = Usuario.query.filter_by(correo='aprendiz.propio@test.local').first()
        ajeno = Usuario.query.filter_by(correo='aprendiz.ajeno@test.local').first()
        return SimpleNamespace(
            admin_id=admin.id_usuario, admin_correo=admin.correo,
            inst_id=inst.id_usuario, inst_correo=inst.correo,
            id_instructor=inst.instructor.id_instructor,
            ap_id=propio.id_usuario, ap_correo=propio.correo,
            id_ap=propio.aprendiz.id_aprendiz,
            ajeno_uid=ajeno.id_usuario, id_ajeno=ajeno.aprendiz.id_aprendiz,
            id_curso=Curso.query.filter_by(ficha='CI0001').first().id_curso,
            ficha='CI0001',
            id_curso2=Curso.query.filter_by(ficha='CI0002').first().id_curso,
            ficha2='CI0002')


@pytest.fixture
def correos(app):
    """Correos que el sistema "envió" durante la prueba."""
    app.correos.clear()
    return app.correos


@pytest.fixture
def avisos(monkeypatch):
    """Avisos por correo que el sistema encola en segundo plano, capturados de
    forma síncrona: cada elemento es el `datos` que recibiría `_entregar`."""
    from app.servicios import correo as serv_correo
    capturados = []

    class HiloSincrono:
        def __init__(self, target, args, daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(serv_correo, 'threading', SimpleNamespace(Thread=HiloSincrono))
    monkeypatch.setattr(serv_correo, '_entregar',
                        lambda app_, datos: capturados.append(datos))
    return capturados


def cliente_de(app, id_usuario):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(id_usuario)
        s['_fresh'] = True
    return c


@pytest.fixture
def c_admin(app, datos):
    return cliente_de(app, datos.admin_id)


@pytest.fixture
def c_inst(app, datos):
    return cliente_de(app, datos.inst_id)


@pytest.fixture
def c_ap(app, datos):
    return cliente_de(app, datos.ap_id)


@pytest.fixture
def anonimo(app):
    return app.test_client()


def token(cliente, url):
    """Extrae el csrf_token de un formulario de la página."""
    html = cliente.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else None


def texto(respuesta):
    return respuesta.get_data(as_text=True)


def enlace_de(correos, pos=-1):
    """URL de confirmación del correo enviado en la posición dada."""
    return re.search(r'https?://\S+/verificar/\S+', correos[pos]['texto']).group(0)
