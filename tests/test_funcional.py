"""Prueba funcional: recorre los flujos reales de cada rol contra una COPIA
de la base de datos, incluyendo POSTs con CSRF, rutas con parámetros,
control de acceso (IDOR) y protección de los archivos de evidencia."""
import os, re, shutil, sys, tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
PROY = os.environ.get('PROY') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROY)

# Copia de la BD para no tocar los datos reales
tmp = tempfile.mkdtemp()
shutil.copy(os.path.join(PROY, 'instance', 'flaskdb.sqlite'),
            os.path.join(tmp, 'copia.sqlite'))
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(tmp, 'copia.sqlite')
os.environ['RUN_DB_INIT'] = '0'
os.environ['SECRET_KEY'] = 'clave-de-prueba'

from app import create_app, db
from app.models.usuario import Usuario
from app.models.curso import Curso
from app.models.evidencia import Evidencia
from app.models.aprendiz import Aprendiz

app = create_app()
app.config['SERVER_NAME'] = 'localhost'
ok, fallos = [], []


def check(nombre, condicion, detalle=''):
    (ok if condicion else fallos).append(nombre)
    print(('  ok   ' if condicion else '  FALLA ') + nombre + (f'  [{detalle}]' if detalle and not condicion else ''))


def cliente(uid):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid); s['_fresh'] = True
    return c


def token(c, url):
    """Extrae un csrf_token de un formulario de la página."""
    html = c.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else None


with app.app_context():
    admin = Usuario.query.filter_by(correo='admin@sena.edu.co').first()
    inst  = next(u for u in Usuario.query.all() if u.instructor)
    aps   = [u for u in Usuario.query.all() if u.aprendiz]
    ap    = aps[0]
    curso = Curso.query.first()
    id_curso = curso.id_curso
    id_ap = ap.aprendiz.id_aprendiz
    ev = Evidencia.query.first()
    id_ev = ev.id_evidencia if ev else None
    # un aprendiz que NO esté en ninguna ficha del instructor
    ids_curso_inst = [ci.id_curso for ci in inst.instructor.cursos]
    from app.models.curso_aprendiz import CursoAprendiz
    ids_suyos = {r[0] for r in db.session.query(CursoAprendiz.id_aprendiz)
                 .filter(CursoAprendiz.id_curso.in_(ids_curso_inst)).all()}
    ajeno = next((a.aprendiz.id_aprendiz for a in aps
                  if a.aprendiz.id_aprendiz not in ids_suyos), None)

c_admin, c_inst, c_ap = cliente(admin.id_usuario), cliente(inst.id_usuario), cliente(ap.id_usuario)

print('\n── Rutas con parámetros ──')
check('admin ve detalle de ficha', c_admin.get(f'/admin/fichas/{id_curso}/detalle').status_code == 200)
r = c_inst.get(f'/instructor/fichas/{id_curso}/detalle')
check('instructor ve detalle de su ficha (o 403 si no es suya)', r.status_code in (200, 403), str(r.status_code))
check('admin exporta aprendices a Excel', c_admin.get('/admin/backup/exportar/aprendices').status_code == 200)
check('admin exporta historial a Excel', c_admin.get('/admin/backup/exportar/historial').status_code == 200)
check('historial pagina', c_admin.get('/admin/historial?page=2').status_code == 200)

print('\n── CSRF ──')
t = token(c_admin, '/admin/empresas')
check('el formulario trae csrf_token', t is not None)
r = c_admin.post('/admin/empresas/crear', data={'nombre': 'Sin Token SA'})
check('POST sin token es rechazado (400)', r.status_code == 400, str(r.status_code))
r = c_admin.post('/admin/empresas/crear',
                 data={'nombre': 'Empresa Prueba', 'csrf_token': t},
                 follow_redirects=True)
check('POST con token funciona', r.status_code == 200 and 'Empresa Prueba' in r.get_data(as_text=True))

print('\n── Validaciones nuevas ──')
t = token(c_admin, '/admin/usuarios')
r = c_admin.post('/admin/usuarios/crear', data={
    'nombres': 'X', 'apellidos': 'Y', 'correo': 'x@y.com',
    'password': '123', 'csrf_token': t}, follow_redirects=True)
check('rechaza contraseña corta', 'al menos 6' in r.get_data(as_text=True))
with app.app_context():
    check('no creó el usuario con contraseña corta',
          Usuario.query.filter_by(correo='x@y.com').first() is None)
r = c_admin.post(f'/admin/usuarios/{admin.id_usuario}/toggle',
                 data={'csrf_token': t}, follow_redirects=True)
check('no permite desactivar la propia cuenta',
      'propia cuenta' in r.get_data(as_text=True))
with app.app_context():
    check('el admin sigue activo',
          db.session.get(Usuario, admin.id_usuario).estado is True)

print('\n── Control de acceso del instructor (IDOR) ──')
if ajeno:
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{ajeno}/horas',
                    data={'estado_practica': 'Finalizada', 'csrf_token': t})
    check('no puede cambiar el estado de un aprendiz ajeno', r.status_code == 403, str(r.status_code))
    r = c_inst.post(f'/instructor/aprendices/{ajeno}/empresa',
                    data={'id_empresa': 1, 'csrf_token': t})
    check('no puede asignar empresa a un aprendiz ajeno', r.status_code == 403, str(r.status_code))
else:
    print('  (todos los aprendices son del instructor: caso no aplicable)')

propio = sorted(ids_suyos)[0] if ids_suyos else None
if propio:
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{propio}/horas',
                    data={'estado_practica': 'Estado Inventado', 'csrf_token': t},
                    follow_redirects=True)
    check('rechaza un estado de práctica inválido', 'inválido' in r.get_data(as_text=True))
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{propio}/horas',
                    data={'estado_practica': 'Aprobado', 'csrf_token': t},
                    follow_redirects=True)
    with app.app_context():
        actual = db.session.get(Aprendiz, propio).estado_practica
        check('acepta un estado válido del formulario', actual == 'Aprobado', actual)

print('\n── Archivos de evidencia ──')
check('acceso directo a /static/uploads bloqueado',
      c_ap.get('/static/uploads/evidencias/Directions_1.pdf').status_code == 404)
with app.app_context():
    ev_arch = Evidencia.query.filter_by(tipo='archivo').first()
if ev_arch:
    idev = ev_arch.id_evidencia
    dueno = next(u for u in aps if u.aprendiz.id_aprendiz == ev_arch.id_aprendiz)
    r = cliente(dueno.id_usuario).get(f'/archivos/evidencia/{idev}')
    check('el dueño descarga su evidencia', r.status_code in (200, 404), str(r.status_code))
    otro = next((u for u in aps if u.aprendiz.id_aprendiz != ev_arch.id_aprendiz), None)
    if otro:
        r = cliente(otro.id_usuario).get(f'/archivos/evidencia/{idev}')
        check('otro aprendiz NO puede descargarla', r.status_code == 403, str(r.status_code))
    check('sin sesión no se puede descargar',
          app.test_client().get(f'/archivos/evidencia/{idev}').status_code in (302, 401))

print('\n── Flujo aprendiz: subir evidencia ──')
import io
with app.app_context():
    antes = Evidencia.query.filter_by(id_aprendiz=id_ap).count()
t = token(c_ap, '/aprendiz/evidencias/subir')
r = c_ap.post('/aprendiz/evidencias/subir', data={
    'tipo': 'texto', 'contenido': 'Evidencia de prueba automatizada',
    'csrf_token': t}, follow_redirects=True)
with app.app_context():
    check('la evidencia de texto se guarda',
          Evidencia.query.filter_by(id_aprendiz=id_ap).count() == antes + 1)
t = token(c_ap, '/aprendiz/evidencias/subir')
r = c_ap.post('/aprendiz/evidencias/subir', data={
    'tipo': 'archivo', 'csrf_token': t,
    'archivo': (io.BytesIO(b'contenido pdf'), 'reporte.pdf')},
    content_type='multipart/form-data', follow_redirects=True)
with app.app_context():
    nueva = (Evidencia.query.filter_by(id_aprendiz=id_ap, tipo='archivo')
             .order_by(Evidencia.id_evidencia.desc()).first())
    check('el archivo subido recibe nombre único',
          nueva is not None and nueva.contenido != 'uploads/evidencias/reporte.pdf'
          and 'reporte' in nueva.contenido,
          nueva.contenido if nueva else 'sin evidencia')
    if nueva:
        ruta = os.path.join(PROY, 'app', 'static', 'uploads', 'evidencias',
                            os.path.basename(nueva.contenido))
        check('el archivo existe en disco', os.path.isfile(ruta))
        os.remove(ruta)  # limpieza
t = token(c_ap, '/aprendiz/evidencias/subir')
r = c_ap.post('/aprendiz/evidencias/subir', data={
    'tipo': 'archivo', 'csrf_token': t,
    'archivo': (io.BytesIO(b'x'), 'virus.exe')},
    content_type='multipart/form-data', follow_redirects=True)
check('rechaza extensión no permitida', 'no permitido' in r.get_data(as_text=True))

print('\n── Flujo instructor: evaluar evidencia ──')
with app.app_context():
    pendiente = (Evidencia.query.filter(Evidencia.id_aprendiz.in_(ids_suyos),
                                        Evidencia.estado == 'Entregada').first())
    id_pend = pendiente.id_evidencia if pendiente else None
if id_pend:
    t = token(c_inst, '/instructor/evidencias/revisar')
    r = c_inst.post(f'/instructor/evidencias/{id_pend}/evaluar',
                    data={'estado': 'Aprobada', 'observaciones': 'Buen trabajo',
                          'csrf_token': t}, follow_redirects=True)
    with app.app_context():
        e = db.session.get(Evidencia, id_pend)
        check('la evidencia queda Aprobada', e.estado == 'Aprobada', e.estado)
        from app.models.notificacion import Notificacion
        check('se notifica al aprendiz',
              Notificacion.query.filter_by(id_usuario=e.aprendiz.usuario.id_usuario)
              .filter(Notificacion.mensaje.like('%Aprobada%')).first() is not None)

print('\n── Páginas de error ──')
r = app.test_client().get('/ruta-que-no-existe')
check('404 renderiza la página de error', r.status_code == 404 and 'no encontrada' in r.get_data(as_text=True))
r = c_ap.get('/admin/dashboard')
check('403 renderiza la página de error', r.status_code == 403 and 'Acceso denegado' in r.get_data(as_text=True))

print('\n── Login y registro (con CSRF) ──')
from werkzeug.security import generate_password_hash
with app.app_context():
    u = db.session.get(Usuario, ap.id_usuario)
    u.password_hash = generate_password_hash('clave-test-123')
    db.session.commit()
    correo_ap = u.correo
anon = app.test_client()
t = token(anon, '/login')
r = anon.post('/login', data={'correo': correo_ap, 'password': 'mala', 'csrf_token': t})
check('login con clave incorrecta falla con mensaje genérico',
      'Correo o contraseña incorrectos' in r.get_data(as_text=True))
t = token(anon, '/login')
r = anon.post('/login', data={'correo': correo_ap, 'password': 'clave-test-123',
                              'perfil': 'aprendiz', 'csrf_token': t})
check('login correcto redirige al panel', r.status_code == 302 and 'aprendiz' in r.headers['Location'],
      r.headers.get('Location', str(r.status_code)))

# ── El perfil elegido debe corresponder al rol de la cuenta ──
otro = app.test_client()
t = token(otro, '/login')
r = otro.post('/login', data={'correo': correo_ap, 'password': 'clave-test-123',
                              'perfil': 'admin', 'csrf_token': t})
check('un aprendiz no entra eligiendo Administrador',
      r.status_code == 200 and 'no es de tipo Administrador' in r.get_data(as_text=True))
with otro.session_transaction() as ses:
    check('y no queda sesión iniciada', '_user_id' not in ses)

t = token(otro, '/login')
r = otro.post('/login', data={'correo': correo_ap, 'password': 'clave-test-123',
                              'perfil': 'instructor', 'csrf_token': t})
check('un aprendiz no entra eligiendo Instructor',
      'no es de tipo Instructor' in r.get_data(as_text=True))
check('el mensaje le indica el perfil correcto',
      'Ingresa como Aprendiz' in r.get_data(as_text=True))

t = token(otro, '/login')
r = otro.post('/login', data={'correo': correo_ap, 'password': 'clave-test-123',
                              'csrf_token': t})
check('sin elegir perfil no deja entrar',
      'Selecciona el tipo de cuenta' in r.get_data(as_text=True))

# El administrador sí entra eligiendo Administrador
adm = app.test_client()
with app.app_context():
    u = db.session.get(Usuario, admin.id_usuario)
    u.password_hash = generate_password_hash('clave-admin-test')
    db.session.commit()
    correo_admin = u.correo
t = token(adm, '/login')
r = adm.post('/login', data={'correo': correo_admin, 'password': 'clave-admin-test',
                             'perfil': 'admin', 'csrf_token': t})
check('el administrador entra eligiendo Administrador',
      r.status_code == 302 and 'admin' in r.headers.get('Location', ''),
      r.headers.get('Location', str(r.status_code)))

# El color de acento del formulario responde al perfil
html = anon.get('/login').get_data(as_text=True)
check('el formulario declara el perfil para el color', 'data-perfil=' in html)

anon2 = app.test_client()
with app.app_context():
    ficha_valida = db.session.get(Curso, id_curso).ficha
t = token(anon2, '/registro')
r = anon2.post('/registro', data={
    'tipo_documento': 'CC', 'numero_documento': '123', 'nombres': 'Nuevo',
    'apellidos': 'Aprendiz', 'correo': 'nuevo.aprendiz@test.com', 'telefono': '300',
    'password': 'clave123', 'confirm_password': 'clave123',
    'codigo_ficha': ficha_valida or '', 'csrf_token': t}, follow_redirects=True)
with app.app_context():
    creado = Usuario.query.filter_by(correo='nuevo.aprendiz@test.com').first()
    check('el registro crea usuario + aprendiz + matrícula',
          creado is not None and creado.aprendiz is not None
          and len(creado.aprendiz.cursos) == 1)

print('\n── CRUD de fichas (admin) ──')
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Ficha Temporal Test', 'ficha': 'ZZ999', 'csrf_token': t},
    follow_redirects=True)
with app.app_context():
    nueva_f = Curso.query.filter_by(nombre='Ficha Temporal Test').first()
    check('crea la ficha', nueva_f is not None)
    id_nueva = nueva_f.id_curso if nueva_f else None
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Ficha Temporal Test', 'ficha': 'ZZ998', 'csrf_token': t},
    follow_redirects=True)
check('rechaza ficha con nombre duplicado', 'Ya existe una ficha' in r.get_data(as_text=True))
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Otra Ficha', 'ficha': 'ZZ999', 'csrf_token': t}, follow_redirects=True)
check('rechaza código de ficha duplicado', 'ese código' in r.get_data(as_text=True))
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Fechas Mal', 'fecha_inicio': '2026-05-01', 'fecha_fin': '2026-01-01',
    'csrf_token': t}, follow_redirects=True)
check('rechaza fecha fin anterior a inicio', 'anterior a la de inicio' in r.get_data(as_text=True))
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Fecha Basura', 'fecha_inicio': 'no-es-fecha', 'csrf_token': t},
    follow_redirects=True)
check('una fecha inválida no tumba la app (antes daba 500)',
      r.status_code == 200 and 'inválido' in r.get_data(as_text=True), str(r.status_code))
if id_nueva:
    # asignar instructor y luego borrar: verifica la limpieza de llaves foráneas
    with app.app_context():
        id_inst = inst.instructor.id_instructor
    t = token(c_admin, '/admin/fichas')
    c_admin.post(f'/admin/fichas/{id_nueva}/asignar-instructor',
                 data={'id_instructor': id_inst, 'csrf_token': t}, follow_redirects=True)
    with app.app_context():
        from app.models.curso_instructor import CursoInstructor
        check('asigna instructor a la ficha',
              CursoInstructor.query.filter_by(id_curso=id_nueva).count() == 1)
    t = token(c_admin, '/admin/fichas')
    r = c_admin.post(f'/admin/fichas/{id_nueva}/eliminar',
                     data={'csrf_token': t}, follow_redirects=True)
    with app.app_context():
        check('elimina la ficha junto con sus asignaciones',
              db.session.get(Curso, id_nueva) is None
              and CursoInstructor.query.filter_by(id_curso=id_nueva).count() == 0)
    t = token(c_admin, '/admin/fichas')
    r = c_admin.post(f'/admin/fichas/{id_curso}/eliminar',
                     data={'csrf_token': t}, follow_redirects=True)
    check('no elimina una ficha con aprendices',
          'aprendices asignados' in r.get_data(as_text=True))

print('\n── Fechas de práctica (instructor) ──')
from datetime import date, timedelta
if propio:
    hoy = date.today()
    ini, fin = hoy - timedelta(days=30), hoy + timedelta(days=70)   # 100 días, 30 corridos
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{propio}/horas', data={
        'estado_practica': 'En proceso', 'csrf_token': t,
        'fecha_inicio_practica': ini.isoformat(),
        'fecha_fin_practica': fin.isoformat()}, follow_redirects=True)
    with app.app_context():
        a = db.session.get(Aprendiz, propio)
        check('guarda la fecha de inicio', a.fecha_inicio_practica == ini, str(a.fecha_inicio_practica))
        check('guarda la fecha de fin', a.fecha_fin_practica == fin, str(a.fecha_fin_practica))
        from app.utils import calcular_progreso
        pr = calcular_progreso(a)
        check('el progreso usa el periodo real, no los 180 días',
              pr['periodo_definido'] and pr['dias_totales'] == 100, str(pr['dias_totales']))
        check('el % de tiempo se calcula sobre ese periodo (30/100 = 30%)',
              pr['pct_tiempo'] == 30.0, str(pr['pct_tiempo']))
        check('calcula los días restantes', pr['dias_restantes'] == 70, str(pr['dias_restantes']))

    # fin anterior al inicio: se rechaza y no se guarda
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{propio}/horas', data={
        'estado_practica': 'En proceso', 'csrf_token': t,
        'fecha_inicio_practica': hoy.isoformat(),
        'fecha_fin_practica': (hoy - timedelta(days=5)).isoformat()}, follow_redirects=True)
    check('rechaza fin anterior al inicio', 'posterior a la de inicio' in r.get_data(as_text=True))
    with app.app_context():
        check('no sobrescribió las fechas válidas',
              db.session.get(Aprendiz, propio).fecha_inicio_practica == ini)

    # fecha con formato basura: no debe dar 500
    t = token(c_inst, '/instructor/aprendices')
    r = c_inst.post(f'/instructor/aprendices/{propio}/horas', data={
        'estado_practica': 'En proceso', 'csrf_token': t,
        'fecha_inicio_practica': 'no-es-fecha'}, follow_redirects=True)
    check('una fecha inválida no rompe la app', r.status_code == 200 and 'inválido' in r.get_data(as_text=True), str(r.status_code))

    # vaciar las fechas vuelve a la estimación automática
    t = token(c_inst, '/instructor/aprendices')
    c_inst.post(f'/instructor/aprendices/{propio}/horas', data={
        'estado_practica': 'En proceso', 'csrf_token': t,
        'fecha_inicio_practica': '', 'fecha_fin_practica': ''}, follow_redirects=True)
    with app.app_context():
        a = db.session.get(Aprendiz, propio)
        pr = calcular_progreso(a)
        check('al vaciarlas vuelve a la estimación de 180 días',
              a.fecha_inicio_practica is None and not pr['periodo_definido']
              and pr['dias_totales'] == 180)

    # un instructor no puede tocar las fechas de un aprendiz ajeno
    if ajeno:
        t = token(c_inst, '/instructor/aprendices')
        r = c_inst.post(f'/instructor/aprendices/{ajeno}/horas', data={
            'estado_practica': 'En proceso', 'csrf_token': t,
            'fecha_inicio_practica': ini.isoformat()})
        check('no puede fijar fechas a un aprendiz ajeno', r.status_code == 403, str(r.status_code))

    # el formulario del detalle de ficha guarda por la misma ruta
    t = token(c_inst, f'/instructor/fichas/{id_curso}/detalle')
    if t:
        r = c_inst.post(f'/instructor/aprendices/{propio}/horas', data={
            'estado_practica': 'En proceso', 'csrf_token': t,
            'fecha_inicio_practica': ini.isoformat(),
            'fecha_fin_practica': fin.isoformat(),
            'next': f'/instructor/fichas/{id_curso}/detalle'})
        check('desde el detalle de ficha vuelve a esa misma página',
              r.status_code == 302 and 'detalle' in r.headers.get('Location', ''),
              r.headers.get('Location', str(r.status_code)))

print('\n── Conexión de Google y avisos por correo ──')
from app.servicios import correo as svc_correo
from app.servicios import google_oauth
from app.models.cuenta_google import CuentaGoogle

# El apartado es visible para aprendiz e instructor
for etiqueta, cli in (('aprendiz', c_ap), ('instructor', c_inst)):
    r = cli.get('/cuenta/conexiones')
    check(f'{etiqueta} accede al apartado de conexiones', r.status_code == 200, str(r.status_code))
html = c_ap.get('/cuenta/conexiones').get_data(as_text=True)
check('sin credenciales avisa que no está disponible', 'Todaví' in html or 'no ha cargado' in html)

# Sin credenciales de Google, conectar no rompe: redirige con aviso
r = c_ap.get('/cuenta/google/conectar', follow_redirects=True)
check('conectar sin credenciales no falla', r.status_code == 200)

# El cifrado del refresh token es reversible y no guarda el valor en claro
with app.app_context():
    app.config['GOOGLE_CLIENT_ID'] = 'demo.apps.googleusercontent.com'
    app.config['GOOGLE_CLIENT_SECRET'] = 'secreto-demo'
    cifrado = google_oauth.cifrar('1//refresh-de-prueba')
    check('el refresh token se guarda cifrado', '1//refresh-de-prueba' not in cifrado)
    check('y se puede descifrar', google_oauth.descifrar(cifrado) == '1//refresh-de-prueba')
    check('esta_configurado detecta las credenciales', google_oauth.esta_configurado())

# El state del OAuth va firmado: uno manipulado se rechaza
r = c_ap.get('/cuenta/google/callback?code=x&state=falsificado')
check('un state inválido se rechaza', r.status_code == 400, str(r.status_code))

# Los avisos se encolan sin tocar la red: se intercepta el hilo de entrega
enviados = []
original = svc_correo._entregar
svc_correo._entregar = lambda app_, datos: enviados.append(datos)
try:
    with app.app_context():
        with app.test_request_context():
            u_ap = db.session.get(Usuario, ap.id_usuario)
            u_in = db.session.get(Usuario, inst.id_usuario)
            svc_correo.avisar_evidencia_subida(u_in, u_ap, 'Ficha Demo', 'archivo')
            svc_correo.avisar_evidencia_calificada(u_ap, u_in, 'Aprobada', 'Buen trabajo', None)
finally:
    svc_correo._entregar = original

check('se encolan los dos avisos', len(enviados) == 2, str(len(enviados)))
if len(enviados) == 2:
    subida, calificada = enviados
    check('el aviso de subida va al instructor', subida['destinatario'] == inst.correo, subida['destinatario'])
    check('el aviso de calificación va al aprendiz', calificada['destinatario'] == ap.correo, calificada['destinatario'])
    check('el asunto de calificación incluye el estado', 'Aprobada' in calificada['asunto'], calificada['asunto'])
    check('las observaciones viajan en el cuerpo', 'Buen trabajo' in calificada['texto'])
    check('sin cuenta de Google el remitente es el institucional',
          subida['refresh_token'] is None)

# Con cuenta vinculada, el remitente pasa a ser la del usuario
with app.app_context():
    cuenta = CuentaGoogle(id_usuario=ap.id_usuario, correo_google='aprendiz@gmail.com',
                          refresh_token=google_oauth.cifrar('token-demo'))
    db.session.add(cuenta); db.session.commit()
enviados.clear()
svc_correo._entregar = lambda app_, datos: enviados.append(datos)
try:
    with app.app_context():
        with app.test_request_context():
            u_ap = db.session.get(Usuario, ap.id_usuario)
            u_in = db.session.get(Usuario, inst.id_usuario)
            svc_correo.avisar_evidencia_subida(u_in, u_ap, 'Ficha Demo', 'texto')
finally:
    svc_correo._entregar = original
check('con cuenta vinculada el correo sale a nombre del usuario',
      enviados and enviados[0]['remitente'] == 'aprendiz@gmail.com',
      enviados[0]['remitente'] if enviados else 'sin envío')

# El panel ya muestra la cuenta conectada y permite desconectarla
html = c_ap.get('/cuenta/conexiones').get_data(as_text=True)
check('el panel muestra la cuenta conectada', 'aprendiz@gmail.com' in html)
t = token(c_ap, '/cuenta/conexiones')
r = c_ap.post('/cuenta/google/desconectar', data={'csrf_token': t}, follow_redirects=True)
with app.app_context():
    check('desconectar elimina la cuenta',
          CuentaGoogle.query.filter_by(id_usuario=ap.id_usuario).first() is None)

print('\n── Eliminar usuarios (admin) ──')
from app.models.historial_cambios import HistorialCambios
from app.models.rol import Rol
from app.models.usuario_rol import UsuarioRol
from app.models.curso_aprendiz import CursoAprendiz as CA2
from app.models.notificacion import Notificacion as Notif2

# Se crea un aprendiz de usar y tirar, con evidencia, matrícula e historial
with app.app_context():
    victima = Usuario(nombres='Borrar', apellidos='Me', correo='borrar.me@test.com',
                      password_hash=generate_password_hash('clave123'), estado=True)
    db.session.add(victima); db.session.flush()
    rol_ap = Rol.query.filter_by(nombre='aprendiz').first()
    db.session.add(UsuarioRol(id_usuario=victima.id_usuario, id_rol=rol_ap.id_rol))
    ap_v = Aprendiz(id_usuario=victima.id_usuario, estado_practica='En proceso')
    db.session.add(ap_v); db.session.flush()
    db.session.add(CA2(id_curso=id_curso, id_aprendiz=ap_v.id_aprendiz))
    db.session.add(Evidencia(id_aprendiz=ap_v.id_aprendiz, tipo='texto',
                             contenido='evidencia de prueba', estado='Entregada'))
    db.session.add(Notif2(id_usuario=victima.id_usuario, mensaje='hola'))
    db.session.add(HistorialCambios(id_usuario=victima.id_usuario, modulo='Prueba',
                                    accion='CREAR', descripcion='rastro de auditoria'))
    db.session.commit()
    id_victima = victima.id_usuario
    id_ap_victima = ap_v.id_aprendiz

html = c_admin.get('/admin/usuarios').get_data(as_text=True)
check('el listado ofrece eliminar', 'modalEliminarUsuario' in html)
check('el modal resume lo que se pierde', 'Se eliminará también' in html)

# Sin la confirmación correcta no se borra nada
t = token(c_admin, '/admin/usuarios')
r = c_admin.post(f'/admin/usuarios/{id_victima}/eliminar',
                 data={'csrf_token': t, 'confirmacion': 'otra-cosa@test.com'},
                 follow_redirects=True)
check('rechaza una confirmación que no coincide', 'no coincide' in r.get_data(as_text=True))
with app.app_context():
    check('y el usuario sigue existiendo', db.session.get(Usuario, id_victima) is not None)

# No puede eliminarse a sí mismo
t = token(c_admin, '/admin/usuarios')
r = c_admin.post(f'/admin/usuarios/{admin.id_usuario}/eliminar',
                 data={'csrf_token': t, 'confirmacion': admin.correo}, follow_redirects=True)
check('no puede eliminar su propia cuenta', 'propia cuenta' in r.get_data(as_text=True))
with app.app_context():
    check('el admin sigue ahí', db.session.get(Usuario, admin.id_usuario) is not None)

# Un instructor no puede llegar a esta ruta
t2 = token(c_inst, '/instructor/aprendices')
r = c_inst.post(f'/admin/usuarios/{id_victima}/eliminar',
                data={'csrf_token': t2, 'confirmacion': 'borrar.me@test.com'})
check('un instructor no puede eliminar usuarios', r.status_code == 403, str(r.status_code))

# Con la confirmación correcta, se borra en cascada
t = token(c_admin, '/admin/usuarios')
r = c_admin.post(f'/admin/usuarios/{id_victima}/eliminar',
                 data={'csrf_token': t, 'confirmacion': 'borrar.me@test.com'},
                 follow_redirects=True)
check('elimina el usuario', 'eliminado definitivamente' in r.get_data(as_text=True))
with app.app_context():
    check('  · el usuario ya no existe', db.session.get(Usuario, id_victima) is None)
    check('  · se borró su perfil de aprendiz', db.session.get(Aprendiz, id_ap_victima) is None)
    check('  · se borraron sus evidencias',
          Evidencia.query.filter_by(id_aprendiz=id_ap_victima).count() == 0)
    check('  · se borró su matrícula en la ficha',
          CA2.query.filter_by(id_aprendiz=id_ap_victima).count() == 0)
    check('  · se borraron sus notificaciones',
          Notif2.query.filter_by(id_usuario=id_victima).count() == 0)
    rastro = HistorialCambios.query.filter_by(descripcion='rastro de auditoria').first()
    check('  · SE CONSERVA su historial de auditoría', rastro is not None)
    check('  · desligado del usuario borrado', rastro is not None and rastro.id_usuario is None)
    check('  · y queda registrado quién lo eliminó',
          HistorialCambios.query.filter(
              HistorialCambios.descripcion.like('%borrar.me@test.com%'),
              HistorialCambios.accion == 'ELIMINAR').first() is not None)

# Volver a enviar el borrado del mismo usuario no da 404, informa y redirige
t = token(c_admin, '/admin/usuarios')
r = c_admin.post(f'/admin/usuarios/{id_victima}/eliminar',
                 data={'csrf_token': t, 'confirmacion': 'borrar.me@test.com'},
                 follow_redirects=True)
check('reenviar el borrado no devuelve 404',
      r.status_code == 200 and 'ya no existe' in r.get_data(as_text=True),
      str(r.status_code))

# El historial se sigue pudiendo abrir y exportar con entradas huérfanas
check('el historial se muestra con entradas sin usuario',
      c_admin.get('/admin/historial').status_code == 200)
check('la exportación a Excel no falla',
      c_admin.get('/admin/backup/exportar/historial').status_code == 200)

# La ficha del curso no se toca al borrar a uno de sus aprendices
with app.app_context():
    check('la ficha sigue existiendo', db.session.get(Curso, id_curso) is not None)

print('\n── Caché y botón de retroceso ──')
r = c_ap.get('/aprendiz/dashboard')
cc = r.headers.get('Cache-Control', '')
check('las páginas privadas no se guardan en caché', 'no-store' in cc, cc)
check('y exigen revalidación', 'must-revalidate' in cc, cc)
check('los estáticos revalidan en vez de cachearse a ciegas',
      c_ap.get('/static/biblioteca.css').headers.get('Cache-Control') == 'no-cache')
check('la página lleva el seguro contra la caché de retroceso',
      'evento.persisted' in r.get_data(as_text=True))

# Tras cambiar de usuario, la misma ruta responde con los datos del nuevo
otro_ap = next((u for u in aps if u.id_usuario != ap.id_usuario), None)
if otro_ap:
    c_otro = cliente(otro_ap.id_usuario)
    html_a = c_ap.get('/aprendiz/informacion').get_data(as_text=True)
    html_b = c_otro.get('/aprendiz/informacion').get_data(as_text=True)
    check('cada sesión ve su propio correo en la misma ruta',
          ap.correo in html_a and otro_ap.correo in html_b
          and otro_ap.correo not in html_a)

print('\n── Páginas legales (públicas) ──')
anon_legal = app.test_client()
for ruta, marca in (('/privacidad', 'gmail.send'), ('/terminos', 'Uso aceptable')):
    r = anon_legal.get(ruta)
    check(f'{ruta} es pública y carga', r.status_code == 200, str(r.status_code))
    check(f'{ruta} tiene el contenido esperado', marca in r.get_data(as_text=True))
html = anon_legal.get('/privacidad').get_data(as_text=True)
check('la privacidad explica que no se lee el buzón', 'no puede leer el buzón' in html)
check('y cómo revocar el permiso', 'myaccount.google.com/permissions' in html)
check('el login enlaza a las páginas legales',
      '/privacidad' in anon_legal.get('/login').get_data(as_text=True))

print('\n── Cabeceras del correo (entregabilidad) ──')
capturados = []
original2 = svc_correo._enviar_smtp
svc_correo._enviar_smtp = lambda cfg, mensaje: capturados.append(mensaje)
try:
    with app.app_context():
        app.config['MAIL_USERNAME'] = 'notificaciones@sena.test'
        app.config['MAIL_PASSWORD'] = 'x'
        with app.test_request_context():
            u_ap = db.session.get(Usuario, ap.id_usuario)
            u_in = db.session.get(Usuario, inst.id_usuario)
            datos_prueba = {
                'destinatario': u_in.correo, 'asunto': 'Prueba', 'texto': 'texto',
                'html': '<p>h</p>', 'refresh_token': None,
                'remitente': 'notificaciones@sena.test',
                'remitente_nombre': 'SENA Prácticas',
                'responder_a': u_ap.correo, 'id_cuenta': None,
            }
            svc_correo._entregar(app, datos_prueba)
finally:
    svc_correo._enviar_smtp = original2

check('se construyó el mensaje', len(capturados) == 1, str(len(capturados)))
if capturados:
    m = capturados[0]
    check('el remitente lleva nombre visible', 'SENA Prácticas' in m['From'], m['From'])
    check('hay dirección de respuesta real', m['Reply-To'] == ap.correo, str(m['Reply-To']))
    check('va marcado como mensaje automático',
          m['Auto-Submitted'] == 'auto-generated', str(m['Auto-Submitted']))
    check('lleva versión en texto plano y en HTML', m.is_multipart())

print('\n── Fichas no asignadas y auto-matrícula ──')
from app.utils import fichas_pendientes, aprendices_sin_matricula
from app.models.notificacion import Notificacion as Notif3

CODIGO_NUEVO = 'ZZ-PENDIENTE-1'
reg = app.test_client()
t = token(reg, '/registro')
r = reg.post('/registro', data={
    'tipo_documento': 'CC', 'numero_documento': '999', 'nombres': 'Ana',
    'apellidos': 'Pendiente', 'correo': 'ana.pendiente@test.com', 'telefono': '300',
    'password': 'clave123', 'confirm_password': 'clave123',
    'codigo_ficha': CODIGO_NUEVO, 'csrf_token': t}, follow_redirects=True)
check('el registro con ficha inexistente ya NO se rechaza',
      'no existe' not in r.get_data(as_text=True))
check('y avisa de que quedará en espera',
      'todav' in r.get_data(as_text=True).lower() or 'espera' in r.get_data(as_text=True).lower())

with app.app_context():
    creada = Usuario.query.filter_by(correo='ana.pendiente@test.com').first()
    check('la cuenta se crea igual', creada is not None and creada.aprendiz is not None)
    check('con el código guardado', creada and creada.aprendiz.ficha == CODIGO_NUEVO)
    check('pero sin matrícula en ningún curso', creada and len(creada.aprendiz.cursos) == 0)
    pend = [f['codigo'] for f in fichas_pendientes()]
    check('aparece como ficha pendiente', CODIGO_NUEVO in pend, str(pend))
    avisos = Notif3.query.filter(Notif3.mensaje.like(f'%{CODIGO_NUEVO}%')).count()
    check('se avisó al administrador', avisos >= 1, str(avisos))

check('el panel de fichas muestra las pendientes',
      CODIGO_NUEVO in c_admin.get('/admin/fichas').get_data(as_text=True))

# Al crear la ficha con ese código, se matricula solo
t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/crear', data={
    'nombre': 'Ficha Recien Creada', 'ficha': CODIGO_NUEVO, 'csrf_token': t},
    follow_redirects=True)
check('al crear la ficha avisa de la matrícula automática',
      'matricularon' in r.get_data(as_text=True))
with app.app_context():
    creada = Usuario.query.filter_by(correo='ana.pendiente@test.com').first()
    check('el aprendiz quedó matriculado solo', len(creada.aprendiz.cursos) == 1)
    check('y ya no figura como pendiente',
          CODIGO_NUEVO not in [f['codigo'] for f in fichas_pendientes()])
    id_ana = creada.id_usuario

# Caso distinto: el código SÍ existe como ficha pero falta la matrícula
with app.app_context():
    curso_real = db.session.get(Curso, id_curso)
    huerfano = Usuario(nombres='Sin', apellidos='Matricula',
                       correo='sin.matricula@test.com',
                       password_hash=generate_password_hash('x'), estado=True)
    db.session.add(huerfano); db.session.flush()
    db.session.add(Aprendiz(id_usuario=huerfano.id_usuario, ficha=curso_real.ficha,
                            estado_practica='En proceso'))
    db.session.commit()
    id_huerfano = huerfano.id_usuario
    grupo = next((f for f in fichas_pendientes() if f['codigo'] == curso_real.ficha), None)
    check('detecta al aprendiz sin matrícula', grupo is not None)
    check('y sabe que esa ficha SÍ existe', grupo and grupo['curso'] is not None)

t = token(c_admin, '/admin/fichas')
r = c_admin.post('/admin/fichas/matricular-pendientes',
                 data={'codigo': curso_real.ficha, 'csrf_token': t}, follow_redirects=True)
check('los matricula sin crear otra ficha', 'matricularon' in r.get_data(as_text=True))
with app.app_context():
    h = db.session.get(Usuario, id_huerfano)
    check('el aprendiz quedó matriculado', len(h.aprendiz.cursos) == 1)
    check('y no se duplicó la ficha',
          Curso.query.filter_by(ficha=curso_real.ficha).count() == 1)

print('\n── El administrador gestiona la ficha del aprendiz ──')
with app.app_context():
    otro_curso = Curso.query.filter(Curso.id_curso != id_curso).first()
t = token(c_admin, '/admin/usuarios')
if otro_curso:
    r = c_admin.post(f'/admin/usuarios/{id_ana}/ficha',
                     data={'id_curso': otro_curso.id_curso, 'csrf_token': t},
                     follow_redirects=True)
    with app.app_context():
        a = db.session.get(Usuario, id_ana)
        check('mueve al aprendiz de ficha',
              len(a.aprendiz.cursos) == 1 and a.aprendiz.cursos[0].id_curso == otro_curso.id_curso)
        check('y sincroniza el código de ficha', a.aprendiz.ficha == otro_curso.ficha)

t = token(c_admin, '/admin/usuarios')
r = c_admin.post(f'/admin/usuarios/{id_ana}/ficha',
                 data={'id_curso': '', 'csrf_token': t}, follow_redirects=True)
with app.app_context():
    a = db.session.get(Usuario, id_ana)
    check('puede dejarlo sin ficha', len(a.aprendiz.cursos) == 0 and a.aprendiz.ficha is None)

t2 = token(c_inst, '/instructor/aprendices')
r = c_inst.post(f'/admin/usuarios/{id_ana}/ficha', data={'id_curso': '', 'csrf_token': t2})
check('un instructor no puede cambiar fichas de usuarios', r.status_code == 403, str(r.status_code))

print('\n── El aprendiz edita sus datos ──')
t = token(c_ap, '/aprendiz/informacion')
r = c_ap.post('/aprendiz/informacion', data={
    'nombres': 'NombreNuevo', 'apellidos': 'ApellidoNuevo', 'correo': ap.correo,
    'telefono': '3001234567', 'tipo_documento': 'TI', 'numero_documento': '55512345',
    'csrf_token': t}, follow_redirects=True)
with app.app_context():
    a = db.session.get(Usuario, ap.id_usuario)
    check('guarda nombres y apellidos', a.nombres == 'NombreNuevo' and a.apellidos == 'ApellidoNuevo')
    check('guarda el documento', a.tipo_documento == 'TI' and a.numero_documento == '55512345')
    ficha_antes = a.aprendiz.ficha

t = token(c_ap, '/aprendiz/informacion')
r = c_ap.post('/aprendiz/informacion', data={
    'nombres': 'NombreNuevo', 'apellidos': 'ApellidoNuevo', 'correo': 'no-es-correo',
    'telefono': '', 'csrf_token': t}, follow_redirects=True)
check('rechaza un correo inválido', 'correo electrónico válido' in r.get_data(as_text=True))

t = token(c_ap, '/aprendiz/informacion')
r = c_ap.post('/aprendiz/informacion', data={
    'nombres': 'X', 'apellidos': 'Y', 'correo': inst.correo,
    'telefono': '', 'csrf_token': t}, follow_redirects=True)
check('rechaza un correo ya usado por otra cuenta', 'Ya existe una cuenta' in r.get_data(as_text=True))

# La ficha no se puede cambiar desde ahí aunque se envíe en el formulario
t = token(c_ap, '/aprendiz/informacion')
c_ap.post('/aprendiz/informacion', data={
    'nombres': 'NombreNuevo', 'apellidos': 'ApellidoNuevo', 'correo': ap.correo,
    'telefono': '', 'ficha': 'INTENTO-DE-CAMBIO', 'csrf_token': t}, follow_redirects=True)
with app.app_context():
    check('el aprendiz NO puede cambiarse la ficha',
          db.session.get(Usuario, ap.id_usuario).aprendiz.ficha == ficha_antes)

print('\n── Armazón y paneles v2 ──')
for etiqueta, cli, ruta, marca in (
    ('aprendiz', c_ap, '/aprendiz/dashboard', 'Mi formación'),
    ('instructor', c_inst, '/instructor/dashboard', 'Cursos y fichas asignadas'),
    ('admin', c_admin, '/admin/dashboard', 'Fichas del centro')):
    html = cli.get(ruta).get_data(as_text=True)
    check(f'panel de {etiqueta} con el diseño nuevo', 'kpi-grid' in html and marca in html)
    check(f'  · {etiqueta} tiene barra lateral', 'lateral-nav' in html)
    check(f'  · {etiqueta} muestra el centro de formación', 'Oriente de Vélez' in html)

html = c_inst.get('/instructor/dashboard').get_data(as_text=True)
check('el rol se muestra como "Instructor", no "InstructorConsole"',
      'InstructorConsole' not in html and '>Instructor<' in html)
html = c_admin.get('/admin/dashboard').get_data(as_text=True)
check('y como "Administrador", no "AdminConsole"',
      'AdminConsole' not in html and 'Administrador' in html)

from app.utils import resumen_curso, iniciales_curso
check('la sigla sale del nombre de la ficha',
      iniciales_curso('Análisis y Desarrollo de Software') == 'ADS',
      iniciales_curso('Análisis y Desarrollo de Software'))
with app.app_context():
    c = db.session.get(Curso, id_curso)
    r = resumen_curso(c)
    check('el resumen de ficha trae estado y avance',
          'estado' in r and 'avance' in r and 0 <= r['avance'] <= 100)

print(f'\nRESULTADO: {len(ok)} ok, {len(fallos)} fallas')
if fallos:
    print('FALLAS:', fallos)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fallos else 0)
