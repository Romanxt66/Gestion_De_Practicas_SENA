"""Panel del instructor: alcance (ficha y asignación directa), fichas propias,
periodo de práctica, evaluación de evidencias, alertas y reportes."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import db
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.empresa import Empresa
from app.models.evidencia import Evidencia
from app.models.historial_cambios import HistorialCambios
from app.models.instructor_aprendiz import InstructorAprendiz
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.utils import calcular_progreso, hoy_local, ids_aprendices_de_instructor
from conftest import cliente_de, crear_curso, crear_usuario, texto, token, unico


def enviar(cliente, pagina, ruta, seguir=True, **campos):
    campos['csrf_token'] = token(cliente, pagina)
    return cliente.post(ruta, data=campos, follow_redirects=seguir)


@pytest.fixture
def equipo(app):
    """Un instructor propio con una ficha, un aprendiz suyo (con una evidencia
    por revisar) y un aprendiz ajeno de otra ficha. Todo desechable."""
    with app.app_context():
        ins = crear_usuario('instructor', nombres='Ines', apellidos='Instructora')
        id_curso = crear_curso(nombre=f'Ficha Propia {unico()}')
        id_otro_curso = crear_curso()
        db.session.add(CursoInstructor(id_curso=id_curso, id_instructor=ins.id_instructor))
        propio = crear_usuario('aprendiz', nombres='Pablo', apellidos='Propio')
        ajeno = crear_usuario('aprendiz', nombres='Aldo', apellidos='Ajeno')
        db.session.add(CursoAprendiz(id_curso=id_curso, id_aprendiz=propio.id_aprendiz))
        db.session.add(CursoAprendiz(id_curso=id_otro_curso, id_aprendiz=ajeno.id_aprendiz))
        ev_propia = Evidencia(id_aprendiz=propio.id_aprendiz, tipo='texto',
                              contenido='mi bitácora', estado='Entregada', documento='bitacora')
        ev_ajena = Evidencia(id_aprendiz=ajeno.id_aprendiz, tipo='texto',
                             contenido='bitácora ajena', estado='Entregada',
                             documento='bitacora')
        db.session.add_all([ev_propia, ev_ajena])
        db.session.commit()
        curso = db.session.get(Curso, id_curso)
        return SimpleNamespace(
            cliente=cliente_de(app, ins.id_usuario), ins=ins, id_curso=id_curso,
            ficha=curso.ficha, nombre_ficha=curso.nombre, id_otro_curso=id_otro_curso,
            propio=propio, ajeno=ajeno, ev_propia=ev_propia.id_evidencia,
            ev_ajena=ev_ajena.id_evidencia)


# ════════════════════════════════════════════════════════════════════════
# Alcance: a quién ve y toca el instructor
# ════════════════════════════════════════════════════════════════════════
def test_mis_aprendices_muestra_solo_a_los_suyos(equipo):
    html = texto(equipo.cliente.get('/instructor/aprendices'))
    assert equipo.propio.correo in html and equipo.ajeno.correo not in html
    assert 'Por ficha' in html and 'a tu cargo' in html


def test_las_otras_vistas_tambien_respetan_el_alcance(equipo):
    for ruta in ('/instructor/progreso', '/instructor/reportes', '/instructor/alertas'):
        html = texto(equipo.cliente.get(ruta))
        assert equipo.propio.correo in html or 'Pablo' in html, ruta
        assert equipo.ajeno.correo not in html and 'Aldo' not in html, ruta


def test_no_puede_tocar_a_un_aprendiz_ajeno(equipo):
    c, aj = equipo.cliente, equipo.ajeno.id_aprendiz
    r = enviar(c, '/instructor/aprendices', f'/instructor/aprendices/{aj}/horas',
               seguir=False, estado_practica='Aprobado')
    assert r.status_code == 403
    r = enviar(c, '/instructor/aprendices', f'/instructor/aprendices/{aj}/empresa',
               seguir=False, id_empresa=1)
    assert r.status_code == 403
    r = enviar(c, '/instructor/aprendices', f'/instructor/aprendices/{aj}/horas',
               seguir=False, estado_practica='En proceso', fecha_inicio_practica='2026-01-01')
    assert r.status_code == 403


def test_asignacion_directa_da_acceso_sin_ficha(app, equipo, c_admin):
    with app.app_context():
        suelto = crear_usuario('aprendiz', nombres='Suelto', apellidos='SinFicha')
    aj = suelto.id_aprendiz
    ruta = f'/instructor/aprendices/{aj}/horas'
    assert enviar(equipo.cliente, '/instructor/aprendices', ruta, seguir=False,
                  estado_practica='Aprobado').status_code == 403

    r = enviar(c_admin, '/admin/usuarios',
               f'/admin/aprendices/{aj}/instructor', id_instructor=equipo.ins.id_instructor)
    assert 'quedó a cargo de' in texto(r)
    with app.app_context():
        assert aj in ids_aprendices_de_instructor(
            db.session.get(Usuario, equipo.ins.id_usuario).instructor)
    assert 'Asignado a ti' in texto(equipo.cliente.get('/instructor/aprendices'))

    r = enviar(equipo.cliente, '/instructor/aprendices', ruta, estado_practica='Aprobado')
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Aprendiz, aj).estado_practica == 'Aprobado'


def test_asignar_dos_veces_no_duplica_y_se_puede_quitar(app, equipo, c_admin):
    with app.app_context():
        suelto = crear_usuario('aprendiz')
    aj, ii = suelto.id_aprendiz, equipo.ins.id_instructor
    ruta = f'/admin/aprendices/{aj}/instructor'
    enviar(c_admin, '/admin/usuarios', ruta, id_instructor=ii)
    assert 'ya tenía asignado' in texto(enviar(c_admin, '/admin/usuarios', ruta, id_instructor=ii))
    with app.app_context():
        assert InstructorAprendiz.query.filter_by(id_instructor=ii, id_aprendiz=aj).count() == 1

    assert 'ya no está asignado' in texto(enviar(c_admin, '/admin/usuarios', f'{ruta}/{ii}/quitar'))
    assert 'ya no estaba asignado' in texto(enviar(c_admin, '/admin/usuarios', f'{ruta}/{ii}/quitar'))
    r = enviar(equipo.cliente, '/instructor/aprendices', f'/instructor/aprendices/{aj}/horas',
               seguir=False, estado_practica='Aprobado')
    assert r.status_code == 403


def test_asignar_instructor_a_aprendiz_sin_elegir_o_inexistente(app, equipo, c_admin):
    ruta = f'/admin/aprendices/{equipo.ajeno.id_aprendiz}/instructor'
    assert 'Selecciona el instructor' in texto(enviar(c_admin, '/admin/usuarios', ruta))
    assert enviar(c_admin, '/admin/usuarios', ruta, id_instructor=999999,
                  seguir=False).status_code == 404
    assert enviar(c_admin, '/admin/usuarios', '/admin/aprendices/999999/instructor',
                  id_instructor=equipo.ins.id_instructor, seguir=False).status_code == 404


def test_un_instructor_no_se_asigna_aprendices_solo(equipo):
    t = token(equipo.cliente, '/instructor/dashboard')
    r = equipo.cliente.post(f'/admin/aprendices/{equipo.ajeno.id_aprendiz}/instructor',
                            data={'id_instructor': equipo.ins.id_instructor, 'csrf_token': t})
    assert r.status_code == 403


def test_un_instructor_puede_llevar_varias_fichas(app, equipo):
    with app.app_context():
        otra = crear_curso()
        db.session.add(CursoInstructor(id_curso=otra, id_instructor=equipo.ins.id_instructor))
        db.session.commit()
        instructor = db.session.get(Usuario, equipo.ins.id_usuario).instructor
        assert len(instructor.cursos) == 2


# ════════════════════════════════════════════════════════════════════════
# Fichas propias
# ════════════════════════════════════════════════════════════════════════
def test_paneles_del_instructor_cargan_con_sus_datos(equipo):
    for ruta in ('/instructor/dashboard', '/instructor/fichas', '/instructor/mis-cursos'):
        r = equipo.cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert equipo.nombre_ficha in texto(r) or ruta == '/instructor/dashboard'


def test_el_dashboard_muestra_el_rol_y_sus_cifras(equipo):
    html = texto(equipo.cliente.get('/instructor/dashboard'))
    assert 'InstructorConsole' not in html and '>Instructor<' in html
    assert equipo.nombre_ficha in html


def test_buscar_entre_sus_fichas(equipo):
    assert equipo.nombre_ficha in texto(equipo.cliente.get(f'/instructor/fichas?q={equipo.ficha}'))
    assert equipo.nombre_ficha not in texto(equipo.cliente.get('/instructor/fichas?q=zzzz-nada'))


def test_crear_ficha_la_deja_a_su_cargo(app, equipo):
    nombre = f'Nueva {unico()}'
    r = enviar(equipo.cliente, '/instructor/fichas', '/instructor/fichas/crear',
               nombre=nombre, ficha=unico('F'), fecha_inicio='2026-01-01', fecha_fin='2026-06-01')
    assert 'creada y asignada' in texto(r)
    with app.app_context():
        curso = Curso.query.filter_by(nombre=nombre).one()
        assert CursoInstructor.query.filter_by(
            id_curso=curso.id_curso, id_instructor=equipo.ins.id_instructor).count() == 1


def test_crear_ficha_vuelve_a_mis_cursos_si_se_pide(equipo):
    r = enviar(equipo.cliente, '/instructor/fichas', '/instructor/fichas/crear?next=instructor.mis_cursos',
               seguir=False, nombre=f'X {unico()}')
    assert r.headers['Location'].endswith('/instructor/mis-cursos')


@pytest.mark.parametrize('campos,mensaje', [
    ({'nombre': ''}, 'El nombre es requerido'),
    ({'nombre': 'Análisis y Desarrollo de Software'}, 'Ya existe una ficha con ese nombre'),
    ({'nombre': 'Otra', 'ficha': 'CI0001'}, 'Ya existe un código de curso'),
    ({'nombre': 'F1', 'fecha_inicio': '2026-05-01', 'fecha_fin': '2026-01-01'}, 'anterior a la de inicio'),
    ({'nombre': 'F2', 'fecha_inicio': 'ayer'}, 'Formato de fecha inválido'),
])
def test_validaciones_al_crear_ficha_propia(equipo, campos, mensaje):
    assert mensaje in texto(enviar(equipo.cliente, '/instructor/fichas',
                                   '/instructor/fichas/crear', **campos))


def test_crear_ficha_matricula_a_los_que_la_esperaban(app, equipo):
    codigo = unico('W-')
    with app.app_context():
        espera = crear_usuario('aprendiz', ficha=codigo)
    r = enviar(equipo.cliente, '/instructor/fichas', '/instructor/fichas/crear',
               nombre=f'Ficha {codigo}', ficha=codigo)
    assert 'Se matricularon' in texto(r)
    with app.app_context():
        assert len(db.session.get(Aprendiz, espera.id_aprendiz).cursos) == 1


def test_detalle_de_su_ficha(equipo):
    r = equipo.cliente.get(f'/instructor/fichas/{equipo.id_curso}/detalle')
    html = texto(r)
    assert r.status_code == 200 and equipo.propio.correo in html
    assert 'Instructores a cargo' in html and '(tú)' in html
    assert 'asignar-instructor' not in html


def test_detalle_de_una_ficha_ajena_es_403_e_inexistente_404(equipo):
    assert equipo.cliente.get(f'/instructor/fichas/{equipo.id_otro_curso}/detalle').status_code == 403
    assert equipo.cliente.get('/instructor/fichas/999999/detalle').status_code == 404


# ════════════════════════════════════════════════════════════════════════
# Empresa del aprendiz
# ════════════════════════════════════════════════════════════════════════
def test_asignar_y_quitar_empresa(app, equipo):
    with app.app_context():
        e = Empresa(nombre=f'Empresa {unico()}', activa=True)
        db.session.add(e)
        db.session.commit()
        id_e = e.id_empresa
    ap, c = equipo.propio.id_aprendiz, equipo.cliente
    r = enviar(c, '/instructor/aprendices', f'/instructor/aprendices/{ap}/empresa', id_empresa=id_e)
    assert 'Empresa asignada correctamente' in texto(r)
    with app.app_context():
        assert db.session.get(Aprendiz, ap).id_empresa == id_e
    r = enviar(c, '/instructor/aprendices', f'/instructor/aprendices/{ap}/empresa', id_empresa='')
    assert 'Empresa removida' in texto(r)
    with app.app_context():
        assert db.session.get(Aprendiz, ap).id_empresa is None


def test_no_asigna_una_empresa_inexistente_o_inactiva(app, equipo):
    with app.app_context():
        e = Empresa(nombre=f'Inactiva {unico()}', activa=False)
        db.session.add(e)
        db.session.commit()
        id_e = e.id_empresa
    ruta = f'/instructor/aprendices/{equipo.propio.id_aprendiz}/empresa'
    for id_empresa in (id_e, 999999):
        r = enviar(equipo.cliente, '/instructor/aprendices', ruta, id_empresa=id_empresa)
        assert 'no existe o está inactiva' in texto(r)


# ════════════════════════════════════════════════════════════════════════
# Estado y periodo de práctica
# ════════════════════════════════════════════════════════════════════════
def horas(equipo, **campos):
    ruta = f'/instructor/aprendices/{equipo.propio.id_aprendiz}/horas'
    return enviar(equipo.cliente, '/instructor/aprendices', ruta, **campos)


def leer(app, equipo):
    with app.app_context():
        a = db.session.get(Aprendiz, equipo.propio.id_aprendiz)
        return a.estado_practica, a.fecha_inicio_practica, a.fecha_fin_practica


def test_cambiar_el_estado_de_practica(app, equipo):
    r = horas(equipo, estado_practica='Aprobado')
    assert 'actualizados correctamente' in texto(r)
    assert leer(app, equipo)[0] == 'Aprobado'


def test_estado_de_practica_invalido(app, equipo):
    assert 'inválido' in texto(horas(equipo, estado_practica='Estado Inventado'))
    assert leer(app, equipo)[0] == 'En proceso'


def test_sin_cambios_lo_avisa(equipo):
    assert 'No hubo cambios' in texto(horas(equipo, estado_practica='En proceso'))


def test_guardar_el_periodo_alimenta_el_progreso(app, equipo):
    with app.app_context():
        hoy = hoy_local()
    ini, fin = hoy - timedelta(days=30), hoy + timedelta(days=70)
    horas(equipo, estado_practica='En proceso',
          fecha_inicio_practica=ini.isoformat(), fecha_fin_practica=fin.isoformat())
    assert leer(app, equipo)[1:] == (ini, fin)
    with app.app_context():
        p = calcular_progreso(db.session.get(Aprendiz, equipo.propio.id_aprendiz))
    assert p['periodo_definido'] and p['dias_totales'] == 100
    assert p['pct_tiempo'] == 30.0 and p['dias_restantes'] == 70


def test_periodo_con_fin_anterior_al_inicio_se_rechaza_y_no_pisa_lo_guardado(app, equipo):
    with app.app_context():
        hoy = hoy_local()
    ini, fin = hoy - timedelta(days=10), hoy + timedelta(days=10)
    horas(equipo, fecha_inicio_practica=ini.isoformat(), fecha_fin_practica=fin.isoformat())
    r = horas(equipo, fecha_inicio_practica=hoy.isoformat(),
              fecha_fin_practica=(hoy - timedelta(days=5)).isoformat())
    assert 'posterior a la de inicio' in texto(r)
    assert leer(app, equipo)[1] == ini


def test_fecha_con_formato_basura_no_rompe_la_app(equipo):
    r = horas(equipo, fecha_inicio_practica='no-es-fecha')
    assert r.status_code == 200 and 'inválido' in texto(r)


def test_vaciar_las_fechas_vuelve_a_la_estimacion_de_180_dias(app, equipo):
    with app.app_context():
        hoy = hoy_local()
    horas(equipo, fecha_inicio_practica=hoy.isoformat(),
          fecha_fin_practica=(hoy + timedelta(days=50)).isoformat())
    horas(equipo, fecha_inicio_practica='', fecha_fin_practica='')
    assert leer(app, equipo)[1:] == (None, None)
    with app.app_context():
        p = calcular_progreso(db.session.get(Aprendiz, equipo.propio.id_aprendiz))
    assert not p['periodo_definido'] and p['dias_totales'] == 180


def test_desde_el_detalle_de_ficha_vuelve_a_esa_pagina(equipo):
    detalle = f'/instructor/fichas/{equipo.id_curso}/detalle'
    r = enviar(equipo.cliente, detalle, f'/instructor/aprendices/{equipo.propio.id_aprendiz}/horas',
               seguir=False, estado_practica='Aprobado', next=detalle)
    assert r.status_code == 302 and r.headers['Location'] == detalle


@pytest.mark.parametrize('destino', ['https://sitio-externo.example/robo', '//sitio-externo.example'])
def test_el_destino_externo_se_ignora(equipo, destino):
    r = horas_sin_seguir(equipo, destino)
    assert 'sitio-externo' not in r.headers['Location']
    assert r.headers['Location'].endswith('/instructor/aprendices')


def horas_sin_seguir(equipo, destino):
    ruta = f'/instructor/aprendices/{equipo.propio.id_aprendiz}/horas'
    return enviar(equipo.cliente, '/instructor/aprendices', ruta, seguir=False,
                  estado_practica='Aprobado', next=destino)


# ════════════════════════════════════════════════════════════════════════
# Revisar y evaluar evidencias
# ════════════════════════════════════════════════════════════════════════
def evaluar(equipo, id_ev, **campos):
    return enviar(equipo.cliente, '/instructor/evidencias/revisar',
                  f'/instructor/evidencias/{id_ev}/evaluar', **campos)


def test_revisar_lista_las_pendientes_propias(equipo):
    html = texto(equipo.cliente.get('/instructor/evidencias/revisar'))
    assert 'mi bitácora' in html or equipo.propio.correo in html
    assert 'bitácora ajena' not in html


def test_un_filtro_desconocido_vuelve_a_pendientes(equipo):
    assert equipo.cliente.get('/instructor/evidencias/revisar?estado=Inventado').status_code == 200


def test_aprobar_una_evidencia(app, equipo, avisos):
    r = evaluar(equipo, equipo.ev_propia, estado='Aprobada', observaciones='Buen trabajo')
    assert 'Evidencia aprobada' in texto(r)
    with app.app_context():
        ev = db.session.get(Evidencia, equipo.ev_propia)
        assert ev.estado == 'Aprobada' and ev.observaciones == 'Buen trabajo'
        aviso = Notificacion.query.filter_by(id_usuario=equipo.propio.id_usuario).one()
        assert 'Aprobada' in aviso.mensaje and 'Buen trabajo' in aviso.mensaje
        assert HistorialCambios.query.filter_by(
            descripcion=f'Evidencia {equipo.ev_propia} calificada como Aprobada').count() == 1


def test_aprobar_avisa_por_correo_al_aprendiz(equipo, avisos):
    evaluar(equipo, equipo.ev_propia, estado='Aprobada', observaciones='Bien')
    assert len(avisos) == 1
    assert avisos[0]['destinatario'] == equipo.propio.correo
    assert 'Aprobada' in avisos[0]['asunto'] and 'Bien' in avisos[0]['texto']
    assert avisos[0]['responder_a'] == equipo.ins.correo


def test_rechazar_una_evidencia(app, equipo, avisos):
    r = evaluar(equipo, equipo.ev_propia, estado='No Aprobada')
    assert 'Evidencia rechazada' in texto(r)
    with app.app_context():
        assert db.session.get(Evidencia, equipo.ev_propia).estado == 'No Aprobada'


def test_las_evaluadas_pasan_a_su_filtro(equipo, avisos):
    evaluar(equipo, equipo.ev_propia, estado='Aprobada')
    assert 'mi bitácora' not in texto(equipo.cliente.get('/instructor/evidencias/revisar'))
    assert 'mi bitácora' in texto(equipo.cliente.get('/instructor/evidencias/revisar?estado=Aprobada'))


def test_estado_de_evaluacion_invalido(app, equipo, avisos):
    r = evaluar(equipo, equipo.ev_propia, estado='Excelente')
    assert 'Estado de evaluación inválido' in texto(r)
    with app.app_context():
        assert db.session.get(Evidencia, equipo.ev_propia).estado == 'Entregada'
    assert avisos == []


def test_no_evalua_evidencias_de_aprendices_ajenos(app, equipo, avisos):
    r = evaluar(equipo, equipo.ev_ajena, estado='Aprobada', seguir=False)
    assert r.status_code == 403
    with app.app_context():
        assert db.session.get(Evidencia, equipo.ev_ajena).estado == 'Entregada'


def test_evaluar_una_evidencia_inexistente(equipo):
    assert evaluar(equipo, 999999, estado='Aprobada', seguir=False).status_code == 404


def test_el_aprendiz_no_evalua(c_ap):
    t = token(c_ap, '/aprendiz/informacion')
    r = c_ap.post('/instructor/evidencias/1/evaluar', data={'estado': 'Aprobada', 'csrf_token': t})
    assert r.status_code == 403


# ════════════════════════════════════════════════════════════════════════
# Alertas
# ════════════════════════════════════════════════════════════════════════
def alerta(equipo, **campos):
    return enviar(equipo.cliente, '/instructor/alertas', '/instructor/alertas', **campos)


def notificaciones(app, id_usuario, mensaje):
    with app.app_context():
        return Notificacion.query.filter_by(id_usuario=id_usuario, mensaje=mensaje).count()


def test_alerta_a_todos_llega_solo_a_sus_aprendices(app, equipo):
    mensaje = f'Reunión {unico()}'
    assert 'Alerta enviada' in texto(alerta(equipo, destino='todos', mensaje=mensaje))
    assert notificaciones(app, equipo.propio.id_usuario, mensaje) == 1
    assert notificaciones(app, equipo.ajeno.id_usuario, mensaje) == 0


def test_alerta_a_un_aprendiz(app, equipo):
    mensaje = f'Aviso {unico()}'
    alerta(equipo, destino=str(equipo.propio.id_usuario), mensaje=mensaje)
    assert notificaciones(app, equipo.propio.id_usuario, mensaje) == 1


def test_alerta_a_un_aprendiz_ajeno_es_403(app, equipo):
    mensaje = f'Intruso {unico()}'
    r = alerta(equipo, destino=str(equipo.ajeno.id_usuario), mensaje=mensaje, seguir=False)
    assert r.status_code == 403
    assert notificaciones(app, equipo.ajeno.id_usuario, mensaje) == 0


def test_alerta_sin_mensaje_o_con_destino_invalido(equipo):
    assert 'Escribe un mensaje' in texto(alerta(equipo, destino='todos', mensaje='  '))
    assert 'Destinatario inválido' in texto(alerta(equipo, destino='abc', mensaje='hola'))


def test_alerta_a_todos_sin_aprendices(app):
    with app.app_context():
        solo = crear_usuario('instructor')
    c = cliente_de(app, solo.id_usuario)
    r = enviar(c, '/instructor/alertas', '/instructor/alertas', destino='todos', mensaje='hola')
    assert 'No tienes aprendices' in texto(r)


# ════════════════════════════════════════════════════════════════════════
# Sin datos y permisos
# ════════════════════════════════════════════════════════════════════════
def test_un_instructor_sin_nada_ve_sus_paneles_vacios(app):
    with app.app_context():
        solo = crear_usuario('instructor')
    c = cliente_de(app, solo.id_usuario)
    for ruta in ('/instructor/dashboard', '/instructor/aprendices', '/instructor/fichas',
                 '/instructor/mis-cursos', '/instructor/evidencias/revisar', '/instructor/alertas',
                 '/instructor/progreso', '/instructor/reportes'):
        assert c.get(ruta).status_code == 200, ruta


def test_el_admin_no_usa_el_panel_del_instructor(c_admin):
    assert c_admin.get('/instructor/dashboard').status_code == 403
