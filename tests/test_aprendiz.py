"""Panel del aprendiz (evidencias, ficha, datos personales, notificaciones) y
descarga protegida de los archivos de evidencia."""
import io
import os
from types import SimpleNamespace

import pytest

from app import db
from app.models.aprendiz import Aprendiz
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.evidencia import Evidencia
from app.models.instructor_aprendiz import InstructorAprendiz
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.utils import directorio_evidencias
from conftest import cliente_de, crear_curso, crear_usuario, texto, token, unico

SUBIR = '/aprendiz/evidencias/subir'


def enviar(cliente, pagina, ruta, seguir=True, **campos):
    campos['csrf_token'] = token(cliente, pagina)
    return cliente.post(ruta, data=campos, follow_redirects=seguir)


@pytest.fixture
def alumno(app):
    """Aprendiz desechable matriculado en una ficha con un instructor."""
    with app.app_context():
        ins = crear_usuario('instructor', nombres='Irene', apellidos='Instructora')
        id_curso = crear_curso(nombre=f'Ficha del alumno {unico()}')
        db.session.add(CursoInstructor(id_curso=id_curso, id_instructor=ins.id_instructor))
        ap = crear_usuario('aprendiz', nombres='Alma', apellidos='Aprendiz')
        db.session.add(CursoAprendiz(id_curso=id_curso, id_aprendiz=ap.id_aprendiz))
        db.session.commit()
        return SimpleNamespace(cliente=cliente_de(app, ap.id_usuario), ap=ap, ins=ins,
                               id_curso=id_curso)


def evidencias_de(app, id_aprendiz, **filtro):
    with app.app_context():
        return (Evidencia.query.filter_by(id_aprendiz=id_aprendiz, **filtro)
                .order_by(Evidencia.id_evidencia).all())


def subir(alumno, **campos):
    return enviar(alumno.cliente, SUBIR, SUBIR, **campos)


def subir_archivo(alumno, nombre, contenido=b'contenido', **campos):
    campos['csrf_token'] = token(alumno.cliente, SUBIR)
    campos['archivo'] = (io.BytesIO(contenido), nombre)
    return alumno.cliente.post(SUBIR, data=campos, content_type='multipart/form-data',
                               follow_redirects=True)


# ════════════════════════════════════════════════════════════════════════
# Subir evidencias
# ════════════════════════════════════════════════════════════════════════
def test_la_vista_muestra_el_plan_de_entregas(alumno):
    html = texto(alumno.cliente.get(SUBIR))
    assert 'plan-entregas' in html and '12 Bitácoras' in html and '3 Actas' in html
    assert 'Formato de planeación de seguimiento' in html
    assert 'accent-purple' not in html and 'badge-purple' not in html


def test_subir_evidencia_de_texto(app, alumno, avisos):
    r = subir(alumno, tipo='texto', documento='bitacora', contenido='Bitácora de la semana 1')
    assert 'Evidencia enviada correctamente' in texto(r)
    ev, = evidencias_de(app, alumno.ap.id_aprendiz)
    assert (ev.tipo, ev.documento, ev.estado) == ('texto', 'bitacora', 'Entregada')
    assert ev.contenido == 'Bitácora de la semana 1'


def test_subir_evidencia_de_enlace(app, alumno, avisos):
    subir(alumno, tipo='enlace', documento='acta', contenido='https://drive.example/acta')
    assert evidencias_de(app, alumno.ap.id_aprendiz)[0].contenido == 'https://drive.example/acta'


def test_subir_un_archivo_le_da_nombre_unico_y_lo_guarda(app, alumno, avisos):
    r = subir_archivo(alumno, 'reporte.pdf', tipo='archivo', documento='acta')
    assert 'Evidencia enviada correctamente' in texto(r)
    ev, = evidencias_de(app, alumno.ap.id_aprendiz, tipo='archivo')
    assert ev.contenido != 'uploads/evidencias/reporte.pdf' and 'reporte' in ev.contenido
    with app.app_context():
        ruta = os.path.join(directorio_evidencias(), os.path.basename(ev.contenido))
    assert os.path.isfile(ruta)
    os.remove(ruta)


def test_dos_aprendices_con_el_mismo_nombre_de_archivo_no_se_pisan(app, alumno, avisos):
    with app.app_context():
        otro = crear_usuario('aprendiz')
    c_otro = cliente_de(app, otro.id_usuario)
    subir_archivo(alumno, 'informe.pdf', b'uno', tipo='archivo', documento='acta')
    campos = {'tipo': 'archivo', 'documento': 'acta', 'csrf_token': token(c_otro, SUBIR),
              'archivo': (io.BytesIO(b'dos'), 'informe.pdf')}
    c_otro.post(SUBIR, data=campos, content_type='multipart/form-data')
    a = evidencias_de(app, alumno.ap.id_aprendiz)[0].contenido
    b = evidencias_de(app, otro.id_aprendiz)[0].contenido
    with app.app_context():
        carpeta = directorio_evidencias()
    try:
        assert a != b
        assert open(os.path.join(carpeta, os.path.basename(a)), 'rb').read() == b'uno'
        assert open(os.path.join(carpeta, os.path.basename(b)), 'rb').read() == b'dos'
    finally:
        for n in (a, b):
            os.remove(os.path.join(carpeta, os.path.basename(n)))


@pytest.mark.parametrize('campos,mensaje', [
    ({'tipo': 'texto', 'contenido': 'Sin documento'}, 'qué documento'),
    ({'tipo': 'texto', 'documento': 'inventado', 'contenido': 'x'}, 'qué documento'),
    ({'tipo': 'texto', 'documento': 'bitacora', 'contenido': '  '}, 'Escribe el contenido'),
    ({'tipo': 'enlace', 'documento': 'acta', 'contenido': 'ftp://servidor/x'}, 'http://'),
    ({'tipo': 'archivo', 'documento': 'acta'}, 'Selecciona un archivo'),
    ({'tipo': 'video', 'documento': 'acta', 'contenido': 'x'}, 'Selecciona un tipo'),
])
def test_validaciones_al_subir(app, alumno, avisos, campos, mensaje):
    assert mensaje in texto(subir(alumno, **campos))
    assert evidencias_de(app, alumno.ap.id_aprendiz) == [] and avisos == []


def test_rechaza_una_extension_no_permitida(app, alumno, avisos):
    r = subir_archivo(alumno, 'virus.exe', tipo='archivo', documento='bitacora')
    assert 'no permitido' in texto(r)
    assert evidencias_de(app, alumno.ap.id_aprendiz) == []


def test_subir_avisa_al_instructor_de_la_ficha(alumno, avisos):
    subir(alumno, tipo='texto', documento='bitacora', contenido='hola')
    assert len(avisos) == 1
    assert avisos[0]['destinatario'] == alumno.ins.correo
    assert 'Nueva evidencia' in avisos[0]['asunto']
    assert avisos[0]['responder_a'] == alumno.ap.correo


def test_subir_avisa_una_sola_vez_por_instructor_y_ficha(app, alumno, avisos):
    with app.app_context():
        otro = crear_usuario('instructor')
        db.session.add(CursoInstructor(id_curso=alumno.id_curso, id_instructor=otro.id_instructor))
        db.session.commit()
    subir(alumno, tipo='texto', documento='bitacora', contenido='hola')
    assert sorted(a['destinatario'] for a in avisos) == sorted([alumno.ins.correo, otro.correo])


def test_subir_sin_instructor_no_avisa_a_nadie(app, avisos):
    with app.app_context():
        ap = crear_usuario('aprendiz')
    c = cliente_de(app, ap.id_usuario)
    enviar(c, SUBIR, SUBIR, tipo='texto', documento='bitacora', contenido='hola')
    assert avisos == []
    assert len(evidencias_de(app, ap.id_aprendiz)) == 1


def test_el_instructor_no_sube_evidencias(c_inst):
    assert c_inst.get(SUBIR).status_code == 403


# ════════════════════════════════════════════════════════════════════════
# Vistas del aprendiz
# ════════════════════════════════════════════════════════════════════════
def test_dashboard_muestra_su_ficha_y_el_rol(alumno):
    r = alumno.cliente.get('/aprendiz/dashboard')
    html = texto(r)
    assert r.status_code == 200 and 'Mi formación' in html and 'lateral-nav' in html


def test_mis_evidencias_lista_solo_las_propias(app, alumno, datos, avisos):
    subir(alumno, tipo='texto', documento='bitacora', contenido='mi-evidencia-propia')
    assert 'mi-evidencia-propia' in texto(alumno.cliente.get('/aprendiz/mis-evidencias'))
    otra = cliente_de(app, datos.ap_id)
    assert 'mi-evidencia-propia' not in texto(otra.get('/aprendiz/mis-evidencias'))


def test_progreso_del_aprendiz(alumno):
    assert alumno.cliente.get('/aprendiz/progreso').status_code == 200


def test_las_notificaciones_se_marcan_como_leidas(app, alumno):
    with app.app_context():
        db.session.add(Notificacion(id_usuario=alumno.ap.id_usuario, mensaje='Aviso importante'))
        db.session.commit()
        assert Notificacion.query.filter_by(id_usuario=alumno.ap.id_usuario, leida=False).count() == 1
    assert 'Aviso importante' in texto(alumno.cliente.get('/aprendiz/notificaciones'))
    with app.app_context():
        assert Notificacion.query.filter_by(id_usuario=alumno.ap.id_usuario, leida=False).count() == 0


# ── Mi ficha ────────────────────────────────────────────────────────────
def test_mi_ficha_muestra_ficha_e_instructor(alumno):
    html = texto(alumno.cliente.get('/aprendiz/mi-ficha'))
    assert 'Ficha del alumno' in html
    assert 'Irene Instructora' in html and alumno.ins.correo in html
    assert 'Compañeros' in html and 'Mi ficha' in html


def test_mi_ficha_incluye_al_instructor_asignado_directamente(app, alumno):
    with app.app_context():
        otra = crear_usuario('instructor', nombres='Otra', apellidos='Directa')
        db.session.add(InstructorAprendiz(id_instructor=otra.id_instructor,
                                          id_aprendiz=alumno.ap.id_aprendiz))
        # el de la ficha también asignado a mano: no debe salir repetido
        db.session.add(InstructorAprendiz(id_instructor=alumno.ins.id_instructor,
                                          id_aprendiz=alumno.ap.id_aprendiz))
        db.session.commit()
    html = texto(alumno.cliente.get('/aprendiz/mi-ficha'))
    assert 'Instructores asignados a ti' in html and 'Otra Directa' in html
    assert html.count('Irene Instructora') == 1


def test_mi_ficha_de_quien_espera_una_ficha_inexistente_lo_explica(app):
    with app.app_context():
        u = crear_usuario('aprendiz', ficha='NO-EXISTE-123')
    html = texto(cliente_de(app, u.id_usuario).get('/aprendiz/mi-ficha'))
    assert 'no está registrada' in html and 'NO-EXISTE-123' in html


def test_mi_ficha_es_solo_para_aprendices(c_inst, c_admin):
    assert c_inst.get('/aprendiz/mi-ficha').status_code == 403
    assert c_admin.get('/aprendiz/mi-ficha').status_code == 403


# ── Mi información ──────────────────────────────────────────────────────
def informacion(alumno, **cambios):
    campos = dict(nombres='Alma', apellidos='Aprendiz', correo=alumno.ap.correo, telefono='')
    campos.update(cambios)
    return enviar(alumno.cliente, '/aprendiz/informacion', '/aprendiz/informacion', **campos)


def usuario(app, alumno):
    with app.app_context():
        u = db.session.get(Usuario, alumno.ap.id_usuario)
        return SimpleNamespace(nombres=u.nombres, apellidos=u.apellidos, correo=u.correo,
                               telefono=u.telefono, tipo_documento=u.tipo_documento,
                               numero_documento=u.numero_documento,
                               ficha=u.aprendiz.ficha)


def test_editar_los_datos_personales(app, alumno):
    r = informacion(alumno, nombres='NombreNuevo', apellidos='ApellidoNuevo',
                    telefono='300 123-4567', tipo_documento='TI', numero_documento='55512345')
    assert 'Datos actualizados' in texto(r)
    u = usuario(app, alumno)
    assert (u.nombres, u.apellidos) == ('NombreNuevo', 'ApellidoNuevo')
    assert (u.tipo_documento, u.numero_documento) == ('TI', '55512345')


def test_cambiar_el_correo_lo_avisa(app, alumno):
    nuevo = f'{unico("n")}@test.local'
    r = informacion(alumno, correo=nuevo.upper())
    assert 'nuevo correo' in texto(r)
    assert usuario(app, alumno).correo == nuevo


@pytest.mark.parametrize('cambios,mensaje', [
    ({'nombres': ''}, 'obligatorios'),
    ({'apellidos': ''}, 'obligatorios'),
    ({'correo': 'no-es-correo'}, 'correo electrónico válido'),
    ({'correo': 'instructor@test.local'}, 'Ya existe una cuenta'),
    ({'telefono': 'abc'}, 'solo puede contener números'),
])
def test_validaciones_de_mi_informacion(app, alumno, cambios, mensaje):
    antes = usuario(app, alumno)
    assert mensaje in texto(informacion(alumno, **cambios))
    assert usuario(app, alumno) == antes


def test_el_aprendiz_no_puede_cambiarse_la_ficha(app, alumno):
    antes = usuario(app, alumno).ficha
    informacion(alumno, ficha='INTENTO-DE-CAMBIO')
    assert usuario(app, alumno).ficha == antes


# ════════════════════════════════════════════════════════════════════════
# Descarga protegida de archivos
# ════════════════════════════════════════════════════════════════════════
@pytest.fixture
def con_archivo(app, alumno):
    """Evidencia de archivo con su fichero real en disco."""
    nombre = f'{unico("prueba")}.pdf'
    with app.app_context():
        ruta = os.path.join(directorio_evidencias(), nombre)
        with open(ruta, 'wb') as f:
            f.write(b'%PDF-contenido-de-prueba')
        ev = Evidencia(id_aprendiz=alumno.ap.id_aprendiz, tipo='archivo',
                       contenido=f'uploads/evidencias/{nombre}', estado='Entregada')
        db.session.add(ev)
        db.session.commit()
        id_ev = ev.id_evidencia
    yield SimpleNamespace(id=id_ev, ruta=ruta, alumno=alumno)
    if os.path.exists(ruta):
        os.remove(ruta)


def test_el_dueno_descarga_su_evidencia(con_archivo):
    r = con_archivo.alumno.cliente.get(f'/archivos/evidencia/{con_archivo.id}')
    assert r.status_code == 200 and r.data == b'%PDF-contenido-de-prueba'


def test_el_instructor_de_la_ficha_y_el_admin_pueden_verla(app, con_archivo, c_admin):
    c_ins = cliente_de(app, con_archivo.alumno.ins.id_usuario)
    assert c_ins.get(f'/archivos/evidencia/{con_archivo.id}').status_code == 200
    assert c_admin.get(f'/archivos/evidencia/{con_archivo.id}').status_code == 200


def test_otros_no_pueden_descargarla(app, con_archivo, datos, c_inst):
    otro_aprendiz = cliente_de(app, datos.ap_id)
    assert otro_aprendiz.get(f'/archivos/evidencia/{con_archivo.id}').status_code == 403
    assert c_inst.get(f'/archivos/evidencia/{con_archivo.id}').status_code == 403


def test_sin_sesion_no_se_puede_descargar(app, con_archivo):
    assert app.test_client().get(f'/archivos/evidencia/{con_archivo.id}').status_code in (302, 401)


def test_evidencia_inexistente_o_sin_archivo(app, alumno):
    assert alumno.cliente.get('/archivos/evidencia/999999').status_code == 404
    with app.app_context():
        ev = Evidencia(id_aprendiz=alumno.ap.id_aprendiz, tipo='texto', contenido='solo texto',
                       estado='Entregada')
        db.session.add(ev)
        db.session.commit()
        id_texto = ev.id_evidencia
    assert alumno.cliente.get(f'/archivos/evidencia/{id_texto}').status_code == 404


def test_archivo_borrado_del_disco_da_404(con_archivo):
    os.remove(con_archivo.ruta)
    assert con_archivo.alumno.cliente.get(f'/archivos/evidencia/{con_archivo.id}').status_code == 404


def test_una_ruta_manipulada_no_sale_de_la_carpeta(app, alumno):
    with app.app_context():
        ev = Evidencia(id_aprendiz=alumno.ap.id_aprendiz, tipo='archivo',
                       contenido='../../../../etc/passwd', estado='Entregada')
        db.session.add(ev)
        db.session.commit()
        id_ev = ev.id_evidencia
    assert alumno.cliente.get(f'/archivos/evidencia/{id_ev}').status_code == 404


def test_uploads_no_se_sirve_como_estatico(con_archivo):
    nombre = os.path.basename(con_archivo.ruta)
    assert con_archivo.alumno.cliente.get(f'/static/uploads/evidencias/{nombre}').status_code == 404
