"""Pruebas unitarias de app/utils.py: permisos, progreso, evidencias, fichas."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import db
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.evidencia import Evidencia
from app.models.historial_cambios import HistorialCambios
from app.models.instructor import Instructor
from app.models.instructor_aprendiz import InstructorAprendiz
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.utils import (
    CATALOGO_EVIDENCIAS, DIAS_PRACTICA, EVIDENCIAS_ESPERADAS,
    aprendices_sin_matricula, avisar_admins_ficha_pendiente, calcular_progreso,
    contar_evidencias_por_aprendiz, desglose_evidencias, es_superusuario,
    evidencias_entregadas_hoy, extension_permitida, fichas_pendientes,
    get_user_role, hoy_local, iniciales_curso, ids_aprendices_de_instructor,
    ids_aprendices_directos, ids_aprendices_por_ficha, ids_cursos_de_instructor,
    indice_aprobacion, instructor_puede_gestionar_aprendiz, log_historial,
    make_aware, matricular_pendientes, nombre_archivo_seguro, origen_de_aprendices,
    progreso_de_aprendices, puede_ver_evidencia, resumen_curso)
from conftest import crear_usuario, unico


# ── Catálogo y constantes ───────────────────────────────────────────────
def test_el_plan_pide_16_documentos():
    assert EVIDENCIAS_ESPERADAS == 16


def test_el_catalogo_se_compone_de_bitacoras_actas_y_planeacion():
    assert {d['clave']: d['cantidad'] for d in CATALOGO_EVIDENCIAS} == {
        'bitacora': 12, 'acta': 3, 'planeacion': 1}


# ── Fechas ──────────────────────────────────────────────────────────────
def test_hoy_local_devuelve_una_fecha(app):
    with app.app_context():
        assert isinstance(hoy_local(), date)


def test_hoy_local_funciona_fuera_de_contexto():
    assert isinstance(hoy_local(), date)


def test_make_aware_agrega_utc_a_un_datetime_ingenuo():
    r = make_aware(datetime(2026, 1, 1, 12, 0))
    assert r.tzinfo is not None and r.utcoffset() == timedelta(0)


def test_make_aware_respeta_los_datetime_con_zona_y_none():
    con_zona = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert make_aware(con_zona) is con_zona
    assert make_aware(None) is None


# ── Roles ───────────────────────────────────────────────────────────────
def test_roles_de_los_usuarios_semilla(app, datos):
    with app.app_context():
        admin = db.session.get(Usuario, datos.admin_id)
        inst = db.session.get(Usuario, datos.inst_id)
        ap = db.session.get(Usuario, datos.ap_id)
        assert get_user_role(admin) == 'superusuario' and es_superusuario(admin)
        assert get_user_role(inst) == 'instructor' and not es_superusuario(inst)
        assert get_user_role(ap) == 'aprendiz' and not es_superusuario(ap)


def test_usuario_sin_rol(app):
    with app.app_context():
        u = Usuario(nombres='S', apellidos='R', correo=f'{unico()}@t.local',
                    password_hash='x')
        db.session.add(u)
        db.session.commit()
        assert get_user_role(u) == 'sin_rol'


# ── Archivos ────────────────────────────────────────────────────────────
@pytest.mark.parametrize('nombre,esperado', [
    ('informe.pdf', True), ('foto.PNG', True), ('datos.xlsx', True),
    ('virus.exe', False), ('script.py', False), ('sin_extension', False),
    ('archivo.tar.gz', False), ('.pdf', True)])
def test_extension_permitida(nombre, esperado):
    assert extension_permitida(nombre) is esperado


def test_nombre_archivo_seguro_conserva_extension_e_incluye_al_aprendiz():
    nombre = nombre_archivo_seguro('informe final.pdf', 7)
    assert nombre.endswith('.pdf') and 'informe_final' in nombre and '_7_' in nombre


def test_nombre_archivo_seguro_evita_recorrido_de_rutas():
    nombre = nombre_archivo_seguro('../../etc/passwd', 1)
    assert '/' not in nombre and '..' not in nombre


def test_nombre_archivo_seguro_sin_nombre_usa_un_valor_por_defecto():
    assert nombre_archivo_seguro('###', 3).startswith('archivo')


def test_nombre_archivo_seguro_recorta_nombres_largos():
    assert len(nombre_archivo_seguro('a' * 300 + '.pdf', 1)) < 120


# ── Fichas: sigla y resumen ─────────────────────────────────────────────
@pytest.mark.parametrize('nombre,sigla', [
    ('Análisis y Desarrollo de Software', 'ADS'),
    ('Gestión de la Producción Agrícola', 'GPA'),
    ('', '—'),
    ('de la y', 'DE '),   # solo palabras vacías: cae a las tres primeras letras
])
def test_iniciales_curso(nombre, sigla):
    assert iniciales_curso(nombre) == sigla


def test_iniciales_curso_limita_a_cuatro_letras():
    assert len(iniciales_curso('Uno Dos Tres Cuatro Cinco Seis')) == 4


def _curso(inicio=None, fin=None, nombre='Curso de Prueba'):
    return SimpleNamespace(nombre=nombre, fecha_inicio=inicio, fecha_fin=fin)


def test_resumen_curso_en_curso(app):
    with app.app_context():
        hoy = hoy_local()
        r = resumen_curso(_curso(hoy - timedelta(days=50), hoy + timedelta(days=50)))
    assert r['estado'] == 'en_curso' and r['avance'] == 50
    assert r['dias_restantes'] == 50 and r['etiqueta'] == 'En curso'


def test_resumen_curso_por_iniciar(app):
    with app.app_context():
        hoy = hoy_local()
        r = resumen_curso(_curso(hoy + timedelta(days=10), hoy + timedelta(days=100)))
    assert r['estado'] == 'proxima' and r['avance'] == 0


def test_resumen_curso_finalizado(app):
    with app.app_context():
        hoy = hoy_local()
        r = resumen_curso(_curso(hoy - timedelta(days=100), hoy - timedelta(days=10)))
    assert r['estado'] == 'finalizada' and r['avance'] == 100
    assert r['dias_restantes'] == 0


def test_resumen_curso_sin_fechas(app):
    with app.app_context():
        r = resumen_curso(_curso())
    assert r['estado'] == 'sin_fechas' and r['avance'] == 0
    assert r['dias_restantes'] is None and r['etiqueta'] == 'Sin fechas'


def test_resumen_curso_con_fechas_incoherentes(app):
    with app.app_context():
        hoy = hoy_local()
        r = resumen_curso(_curso(hoy, hoy - timedelta(days=5)))
    assert r['estado'] == 'sin_fechas' and r['etiqueta'] == 'Fechas por corregir'


def test_resumen_curso_trae_la_sigla(app):
    with app.app_context():
        r = resumen_curso(_curso(nombre='Análisis y Desarrollo de Software'))
    assert r['iniciales'] == 'ADS'


# ── Progreso ────────────────────────────────────────────────────────────
def _aprendiz_falso(inicio=None, fin=None, creado=None):
    usuario = SimpleNamespace(fecha_creacion=creado or datetime.now(timezone.utc))
    return SimpleNamespace(id_aprendiz=0, usuario=usuario,
                           fecha_inicio_practica=inicio, fecha_fin_practica=fin)


def test_progreso_de_un_aprendiz_inexistente_es_cero():
    r = calcular_progreso(None)
    assert r['pct_general'] == 0 and r['dias_totales'] == DIAS_PRACTICA
    assert r['periodo_definido'] is False


def test_progreso_usa_el_periodo_real(app):
    with app.app_context():
        hoy = hoy_local()
        ap = _aprendiz_falso(hoy - timedelta(days=30), hoy + timedelta(days=70))
        r = calcular_progreso(ap, evidencias_count=8)
    assert r['periodo_definido'] and r['dias_totales'] == 100
    assert r['pct_tiempo'] == 30.0 and r['dias_restantes'] == 70
    assert r['pct_evidencias'] == 50.0          # 8 de 16
    assert r['pct_general'] == 40.0             # promedio de 30 y 50


def test_progreso_sin_periodo_estima_180_dias_desde_la_creacion(app):
    with app.app_context():
        ap = _aprendiz_falso(creado=datetime.now(timezone.utc) - timedelta(days=90))
        r = calcular_progreso(ap, evidencias_count=0)
    assert not r['periodo_definido'] and r['dias_totales'] == 180
    assert r['pct_tiempo'] == 50.0 and r['dias_restantes'] == 90


def test_progreso_no_pasa_de_100(app):
    with app.app_context():
        hoy = hoy_local()
        ap = _aprendiz_falso(hoy - timedelta(days=500), hoy - timedelta(days=100))
        r = calcular_progreso(ap, evidencias_count=99)
    assert r['pct_tiempo'] == 100 and r['pct_evidencias'] == 100
    assert r['dias_restantes'] == 0 and r['dias_transcurridos'] == r['dias_totales']


def test_progreso_antes_de_empezar_no_es_negativo(app):
    with app.app_context():
        hoy = hoy_local()
        ap = _aprendiz_falso(hoy + timedelta(days=10), hoy + timedelta(days=110))
        r = calcular_progreso(ap, evidencias_count=0)
    assert r['pct_tiempo'] == 0 and r['dias_transcurridos'] == 0


def test_progreso_ignora_un_periodo_invertido(app):
    with app.app_context():
        hoy = hoy_local()
        ap = _aprendiz_falso(hoy, hoy - timedelta(days=5))
        r = calcular_progreso(ap, evidencias_count=0)
    assert not r['periodo_definido'] and r['dias_totales'] == DIAS_PRACTICA


def test_progreso_cuenta_las_evidencias_de_la_base(app):
    with app.app_context():
        nuevo = crear_usuario('aprendiz')
        for _ in range(4):
            db.session.add(Evidencia(id_aprendiz=nuevo.id_aprendiz, tipo='texto',
                                     contenido='x', estado='Entregada',
                                     documento='bitacora'))
        db.session.commit()
        ap = db.session.get(Aprendiz, nuevo.id_aprendiz)
        r = calcular_progreso(ap)
    assert r['evidencias_count'] == 4 and r['pct_evidencias'] == 25.0


# ── Evidencias ──────────────────────────────────────────────────────────
def test_desglose_de_un_aprendiz_sin_evidencias(app):
    with app.app_context():
        nuevo = crear_usuario('aprendiz')
        d = desglose_evidencias(nuevo.id_aprendiz)
    assert d['total_esperado'] == 16 and d['total_entregado'] == 0
    assert d['sin_clasificar'] == 0
    assert all(x['entregadas'] == 0 and not x['completo'] for x in d['detalle'])


def test_desglose_cuenta_por_documento_y_separa_las_antiguas(app):
    with app.app_context():
        nuevo = crear_usuario('aprendiz')
        for doc in ('bitacora', 'bitacora', 'acta', None):
            db.session.add(Evidencia(id_aprendiz=nuevo.id_aprendiz, tipo='texto',
                                     contenido='x', estado='Entregada', documento=doc))
        db.session.commit()
        d = desglose_evidencias(nuevo.id_aprendiz)
    por_clave = {x['clave']: x for x in d['detalle']}
    assert por_clave['bitacora']['entregadas'] == 2
    assert por_clave['bitacora']['faltan'] == 10
    assert por_clave['acta']['entregadas'] == 1
    assert por_clave['planeacion']['entregadas'] == 0
    assert d['sin_clasificar'] == 1 and d['total_entregado'] == 3


def test_desglose_marca_completo_un_documento(app):
    with app.app_context():
        nuevo = crear_usuario('aprendiz')
        db.session.add(Evidencia(id_aprendiz=nuevo.id_aprendiz, tipo='texto',
                                 contenido='x', estado='Entregada',
                                 documento='planeacion'))
        db.session.commit()
        d = desglose_evidencias(nuevo.id_aprendiz)
    assert next(x for x in d['detalle'] if x['clave'] == 'planeacion')['completo']


def test_desglose_sin_id_no_falla(app):
    with app.app_context():
        assert desglose_evidencias(None)['total_entregado'] == 0


def test_contar_evidencias_por_aprendiz_incluye_a_los_que_no_tienen(app):
    with app.app_context():
        a, b = crear_usuario('aprendiz'), crear_usuario('aprendiz')
        db.session.add_all([
            Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto', contenido='x',
                      estado='Entregada'),
            Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto', contenido='y',
                      estado='Aprobada')])
        db.session.commit()
        todas = contar_evidencias_por_aprendiz([a.id_aprendiz, b.id_aprendiz])
        entregadas = contar_evidencias_por_aprendiz([a.id_aprendiz, b.id_aprendiz],
                                                    estado='Entregada')
    assert todas == {a.id_aprendiz: 2, b.id_aprendiz: 0}
    assert entregadas == {a.id_aprendiz: 1, b.id_aprendiz: 0}


def test_contar_evidencias_con_lista_vacia(app):
    with app.app_context():
        assert contar_evidencias_por_aprendiz([]) == {}


def test_progreso_de_aprendices_devuelve_una_fila_por_aprendiz(app):
    with app.app_context():
        a, b = crear_usuario('aprendiz'), crear_usuario('aprendiz')
        db.session.add(Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto',
                                 contenido='x', estado='Entregada'))
        db.session.commit()
        filas = progreso_de_aprendices([db.session.get(Aprendiz, a.id_aprendiz),
                                        db.session.get(Aprendiz, b.id_aprendiz)])
    assert [f['evidencias_count'] for f in filas] == [1, 0]
    assert {'pct_general', 'pct_tiempo', 'dias_restantes'} <= set(filas[0])


def test_indice_de_aprobacion(app):
    with app.app_context():
        a = crear_usuario('aprendiz')
        for estado in ('Aprobada', 'Aprobada', 'No Aprobada', 'Entregada'):
            db.session.add(Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto',
                                     contenido='x', estado=estado))
        db.session.commit()
        assert indice_aprobacion([a.id_aprendiz]) == 66.7


def test_indice_de_aprobacion_sin_calificadas_es_none(app):
    with app.app_context():
        a = crear_usuario('aprendiz')
        db.session.add(Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto',
                                 contenido='x', estado='Entregada'))
        db.session.commit()
        assert indice_aprobacion([a.id_aprendiz]) is None
        assert indice_aprobacion([]) is None


def test_evidencias_entregadas_hoy(app):
    with app.app_context():
        a = crear_usuario('aprendiz')
        db.session.add_all([
            Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto', contenido='hoy',
                      estado='Entregada'),
            Evidencia(id_aprendiz=a.id_aprendiz, tipo='texto', contenido='antigua',
                      estado='Entregada',
                      fecha_entrega=datetime.now(timezone.utc) - timedelta(days=3))])
        db.session.commit()
        assert evidencias_entregadas_hoy([a.id_aprendiz]) == 1
        assert evidencias_entregadas_hoy([]) == 0


# ── Permisos del instructor ─────────────────────────────────────────────
def _escenario():
    """Instructor con una ficha (aprendiz `por_ficha`), un aprendiz directo,
    uno que llega por las dos vías y uno ajeno. Devuelve ids."""
    ins = crear_usuario('instructor')
    por_ficha = crear_usuario('aprendiz')
    directo = crear_usuario('aprendiz')
    ambos = crear_usuario('aprendiz')
    ajeno = crear_usuario('aprendiz')
    curso = Curso(nombre='Ficha Escenario', ficha=unico('E'))
    db.session.add(curso)
    db.session.flush()
    db.session.add(CursoInstructor(id_curso=curso.id_curso,
                                   id_instructor=ins.id_instructor))
    db.session.add(CursoAprendiz(id_curso=curso.id_curso, id_aprendiz=por_ficha.id_aprendiz))
    db.session.add(CursoAprendiz(id_curso=curso.id_curso, id_aprendiz=ambos.id_aprendiz))
    db.session.add(InstructorAprendiz(id_instructor=ins.id_instructor,
                                      id_aprendiz=directo.id_aprendiz))
    db.session.add(InstructorAprendiz(id_instructor=ins.id_instructor,
                                      id_aprendiz=ambos.id_aprendiz))
    db.session.commit()
    return SimpleNamespace(ins=ins, por_ficha=por_ficha, directo=directo,
                           ambos=ambos, ajeno=ajeno, id_curso=curso.id_curso)


def test_ids_de_los_cursos_del_instructor(app):
    with app.app_context():
        e = _escenario()
        instructor = db.session.get(Instructor, e.ins.id_instructor)
        assert ids_cursos_de_instructor(instructor) == [e.id_curso]
        assert ids_cursos_de_instructor(None) == []


def test_aprendices_por_ficha_y_directos(app):
    with app.app_context():
        e = _escenario()
        instructor = db.session.get(Instructor, e.ins.id_instructor)
        assert ids_aprendices_por_ficha(instructor) == {
            e.por_ficha.id_aprendiz, e.ambos.id_aprendiz}
        assert ids_aprendices_directos(instructor) == {
            e.directo.id_aprendiz, e.ambos.id_aprendiz}


def test_aprendices_a_cargo_suman_las_dos_vias_sin_duplicar(app):
    with app.app_context():
        e = _escenario()
        instructor = db.session.get(Instructor, e.ins.id_instructor)
        a_cargo = ids_aprendices_de_instructor(instructor)
        assert a_cargo == sorted({e.por_ficha.id_aprendiz, e.directo.id_aprendiz,
                                  e.ambos.id_aprendiz})
        assert e.ajeno.id_aprendiz not in a_cargo


def test_origen_de_los_aprendices(app):
    with app.app_context():
        e = _escenario()
        origen = origen_de_aprendices(db.session.get(Instructor, e.ins.id_instructor))
        assert origen[e.por_ficha.id_aprendiz] == 'ficha'
        assert origen[e.directo.id_aprendiz] == 'directo'
        assert origen[e.ambos.id_aprendiz] == 'ambos'
        assert e.ajeno.id_aprendiz not in origen


def test_funciones_de_alcance_sin_instructor(app):
    with app.app_context():
        assert ids_aprendices_de_instructor(None) == []
        assert ids_aprendices_directos(None) == set()
        assert ids_aprendices_por_ficha(None) == set()


def test_instructor_solo_gestiona_a_sus_aprendices(app):
    with app.app_context():
        e = _escenario()
        usuario = db.session.get(Usuario, e.ins.id_usuario)
        assert instructor_puede_gestionar_aprendiz(usuario, e.por_ficha.id_aprendiz)
        assert instructor_puede_gestionar_aprendiz(usuario, e.directo.id_aprendiz)
        assert not instructor_puede_gestionar_aprendiz(usuario, e.ajeno.id_aprendiz)


def test_superusuario_gestiona_a_cualquiera(app, datos):
    with app.app_context():
        admin = db.session.get(Usuario, datos.admin_id)
        assert instructor_puede_gestionar_aprendiz(admin, datos.id_ajeno)


def test_quien_puede_ver_una_evidencia(app, datos):
    with app.app_context():
        e = _escenario()
        ev = Evidencia(id_aprendiz=e.por_ficha.id_aprendiz, tipo='texto',
                       contenido='x', estado='Entregada')
        db.session.add(ev)
        db.session.commit()
        dueno = db.session.get(Usuario, e.por_ficha.id_usuario)
        su_instructor = db.session.get(Usuario, e.ins.id_usuario)
        otro_aprendiz = db.session.get(Usuario, e.ajeno.id_usuario)
        otro_instructor = db.session.get(Usuario, datos.inst_id)
        admin = db.session.get(Usuario, datos.admin_id)
        assert puede_ver_evidencia(dueno, ev)
        assert puede_ver_evidencia(su_instructor, ev)
        assert puede_ver_evidencia(admin, ev)
        assert not puede_ver_evidencia(otro_aprendiz, ev)
        assert not puede_ver_evidencia(otro_instructor, ev)


# ── Fichas pendientes ───────────────────────────────────────────────────
def test_aprendiz_con_ficha_inexistente_queda_pendiente(app):
    codigo = unico('P-')
    with app.app_context():
        nuevo = crear_usuario('aprendiz', ficha=codigo)
        assert nuevo.id_aprendiz in [a.id_aprendiz for a in aprendices_sin_matricula(codigo)]
        grupo = next(f for f in fichas_pendientes() if f['codigo'] == codigo)
        assert grupo['curso'] is None and len(grupo['aprendices']) == 1


def test_aprendiz_sin_codigo_de_ficha_no_es_pendiente(app):
    with app.app_context():
        nuevo = crear_usuario('aprendiz', ficha=None)
        assert nuevo.id_aprendiz not in [a.id_aprendiz for a in aprendices_sin_matricula()]


def test_pendiente_cuyo_curso_ya_existe_se_distingue(app):
    codigo = unico('P-')
    with app.app_context():
        crear_usuario('aprendiz', ficha=codigo)
        db.session.add(Curso(nombre=f'Curso {codigo}', ficha=codigo))
        db.session.commit()
        grupo = next(f for f in fichas_pendientes() if f['codigo'] == codigo)
        assert grupo['curso'] is not None


def test_matricular_pendientes_al_crear_la_ficha(app):
    codigo = unico('P-')
    with app.app_context():
        a, b = crear_usuario('aprendiz', ficha=codigo), crear_usuario('aprendiz', ficha=codigo)
        curso = Curso(nombre=f'Curso {codigo}', ficha=codigo)
        db.session.add(curso)
        db.session.flush()
        matriculados = matricular_pendientes(curso)
        db.session.commit()
        assert {m.id_aprendiz for m in matriculados} == {a.id_aprendiz, b.id_aprendiz}
        assert CursoAprendiz.query.filter_by(id_curso=curso.id_curso).count() == 2
        assert aprendices_sin_matricula(codigo) == []


def test_matricular_pendientes_sin_curso_o_sin_codigo(app):
    with app.app_context():
        assert matricular_pendientes(None) == []
        assert matricular_pendientes(SimpleNamespace(ficha=None, id_curso=1)) == []


def test_avisar_a_los_admins_de_una_ficha_pendiente(app, datos):
    codigo = unico('N-')
    with app.app_context():
        nuevo = crear_usuario('aprendiz', ficha=codigo, nombres='Luz', apellidos='Nueva')
        usuario = db.session.get(Usuario, nuevo.id_usuario)
        avisar_admins_ficha_pendiente(codigo, usuario)
        db.session.commit()
        avisos = Notificacion.query.filter(
            Notificacion.id_usuario == datos.admin_id,
            Notificacion.mensaje.like(f'%{codigo}%')).all()
        assert len(avisos) == 1 and 'Luz Nueva' in avisos[0].mensaje


# ── Auditoría ───────────────────────────────────────────────────────────
def test_log_historial_registra_la_accion_en_mayusculas(app, datos):
    marca = unico('auditoria-')
    with app.app_context():
        admin = db.session.get(Usuario, datos.admin_id)
        log_historial(admin, 'Pruebas', 'crear', marca)
        db.session.commit()
        h = HistorialCambios.query.filter_by(descripcion=marca).one()
        assert h.accion == 'CREAR' and h.modulo == 'Pruebas'
        assert h.id_usuario == datos.admin_id
