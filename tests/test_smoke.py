"""Humo: todas las rutas GET sin parámetros, por rol, sin errores 5xx, y con
el control de acceso por rol funcionando."""
import pytest

from conftest import cliente_de


def rutas_get(app):
    return sorted({str(r) for r in app.url_map.iter_rules()
                   if 'GET' in r.methods and '<' not in str(r)
                   and not str(r).startswith('/static')})


def sin_errores_5xx(app, cliente):
    return [(ruta, c) for ruta in rutas_get(app)
            if (c := cliente.get(ruta).status_code) >= 500]


def test_hay_rutas_que_probar(app):
    assert len(rutas_get(app)) > 20


def test_anonimo_sin_errores_5xx(app, anonimo):
    assert sin_errores_5xx(app, anonimo) == []


def test_admin_sin_errores_5xx(app, c_admin):
    assert sin_errores_5xx(app, c_admin) == []


def test_instructor_sin_errores_5xx(app, c_inst):
    assert sin_errores_5xx(app, c_inst) == []


def test_aprendiz_sin_errores_5xx(app, c_ap):
    assert sin_errores_5xx(app, c_ap) == []


@pytest.mark.parametrize('ruta', [
    '/admin/dashboard', '/admin/usuarios', '/admin/fichas', '/admin/instructores',
    '/admin/empresas', '/admin/roles', '/admin/historial', '/admin/backup'])
def test_solo_el_admin_entra_al_panel_admin(ruta, c_admin, c_inst, c_ap, anonimo):
    assert c_admin.get(ruta).status_code == 200
    assert c_inst.get(ruta).status_code == 403
    assert c_ap.get(ruta).status_code == 403
    assert anonimo.get(ruta).status_code in (301, 302, 401)


@pytest.mark.parametrize('ruta', [
    '/instructor/dashboard', '/instructor/aprendices', '/instructor/fichas',
    '/instructor/mis-cursos', '/instructor/evidencias/revisar', '/instructor/alertas',
    '/instructor/progreso', '/instructor/reportes'])
def test_panel_instructor_solo_para_instructor(ruta, c_inst, c_ap, anonimo):
    assert c_inst.get(ruta).status_code == 200
    assert c_ap.get(ruta).status_code == 403
    assert anonimo.get(ruta).status_code in (301, 302, 401)


@pytest.mark.parametrize('ruta', [
    '/aprendiz/dashboard', '/aprendiz/evidencias/subir', '/aprendiz/informacion',
    '/aprendiz/mi-ficha', '/aprendiz/mis-evidencias', '/aprendiz/notificaciones',
    '/aprendiz/progreso'])
def test_panel_aprendiz_solo_para_aprendiz(ruta, c_ap, c_inst, anonimo):
    assert c_ap.get(ruta).status_code == 200
    assert c_inst.get(ruta).status_code == 403
    assert anonimo.get(ruta).status_code in (301, 302, 401)


@pytest.mark.parametrize('ruta', ['/login', '/registro', '/privacidad', '/terminos'])
def test_paginas_publicas(ruta, anonimo):
    assert anonimo.get(ruta).status_code == 200


def test_la_raiz_lleva_al_portal_de_acceso(anonimo):
    r = anonimo.get('/')
    assert r.status_code in (301, 302)
    assert '/login' in r.headers['Location']


def test_404_y_403_usan_la_pagina_de_error(anonimo, c_ap):
    r = anonimo.get('/ruta-que-no-existe')
    assert r.status_code == 404 and 'no encontrada' in r.get_data(as_text=True)
    r = c_ap.get('/admin/dashboard')
    assert r.status_code == 403 and 'Acceso denegado' in r.get_data(as_text=True)


def test_las_paginas_privadas_no_se_guardan_en_cache(c_ap):
    cc = c_ap.get('/aprendiz/dashboard').headers.get('Cache-Control', '')
    assert 'no-store' in cc and 'must-revalidate' in cc


def test_cabeceras_de_seguridad(anonimo):
    h = anonimo.get('/login').headers
    assert h['X-Content-Type-Options'] == 'nosniff'
    assert h['X-Frame-Options'] == 'SAMEORIGIN'


def test_uploads_no_son_publicos(c_ap):
    assert c_ap.get('/static/uploads/evidencias/cualquiera.pdf').status_code == 404


def test_dos_sesiones_ven_cada_una_su_correo(app, datos, c_ap):
    otro = cliente_de(app, datos.ajeno_uid)
    html_a = c_ap.get('/aprendiz/informacion').get_data(as_text=True)
    html_b = otro.get('/aprendiz/informacion').get_data(as_text=True)
    assert datos.ap_correo in html_a and datos.ap_correo not in html_b
    assert 'aprendiz.ajeno@test.local' in html_b
