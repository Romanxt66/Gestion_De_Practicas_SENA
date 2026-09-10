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

print(f'\nRESULTADO: {len(ok)} ok, {len(fallos)} fallas')
if fallos:
    print('FALLAS:', fallos)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fallos else 0)
