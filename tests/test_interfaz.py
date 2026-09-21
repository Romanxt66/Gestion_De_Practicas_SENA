"""Interfaz: armazón de los paneles, tablas compactas, portal de acceso, panel
móvil y sistema visual (hoja biblioteca.css). Son comprobaciones de marcado y
de estilos: fallan si alguien retira una pieza del diseño sin querer."""
import os

import pytest

from conftest import RAIZ, texto


def leer(*partes):
    with open(os.path.join(RAIZ, *partes), encoding='utf-8') as f:
        return f.read()


@pytest.fixture(scope='module')
def css():
    return leer('app', 'static', 'biblioteca.css')


# ── Armazón de los paneles ──────────────────────────────────────────────
@pytest.mark.parametrize('cliente,ruta,marca', [
    ('c_ap', '/aprendiz/dashboard', 'Mi formación'),
    ('c_inst', '/instructor/dashboard', 'Cursos y fichas asignadas'),
    ('c_admin', '/admin/dashboard', 'Fichas del centro'),
])
def test_paneles_con_el_diseno_nuevo(request, cliente, ruta, marca):
    html = texto(request.getfixturevalue(cliente).get(ruta))
    assert 'kpi-grid' in html and marca in html
    assert 'lateral-nav' in html
    assert 'Oriente de Vélez' in html


def test_el_rol_se_muestra_con_su_nombre_legible(c_inst, c_admin):
    html = texto(c_inst.get('/instructor/dashboard'))
    assert 'InstructorConsole' not in html and '>Instructor<' in html
    html = texto(c_admin.get('/admin/dashboard'))
    assert 'AdminConsole' not in html and 'Administrador' in html


# ── Tablas sin desplazamiento lateral ───────────────────────────────────
def test_existe_el_sistema_de_tabla_compacta(css):
    assert '.tabla-compacta' in css and '.btn-icono' in css
    assert 'white-space: nowrap;\n}' not in css.split('.tabla-compacta')[1][:400]
    assert '.oculta-estrecho' in css and 'max-width: 1199.98px' in css


@pytest.mark.parametrize('plantilla', [
    'admin/usuarios', 'admin/historial', 'admin/roles', 'instructor/aprendices',
    'instructor/revisar_evidencias', 'instructor/reportes', 'aprendiz/mis_evidencias'])
def test_las_plantillas_usan_la_tabla_compacta(plantilla):
    assert 'tabla-compacta' in leer('app', 'templates', f'{plantilla}.html')


def test_la_tabla_de_usuarios_agrupa_los_datos(c_admin):
    html = texto(c_admin.get('/admin/usuarios'))
    assert html.count('<th') - html.count('</th') == 0
    assert 'celda-persona' in html and 'persona-avatar' in html
    cuerpo = html[html.index('<tbody>'):html.index('</tbody>')]
    assert 'btn-icono' in cuerpo and '> Editar' not in cuerpo
    assert '> Bloquear' not in cuerpo and 'btn btn-sm' not in cuerpo
    assert 'tabla-pie' in html


def test_la_tabla_del_instructor_tambien(c_inst):
    html = texto(c_inst.get('/instructor/aprendices'))
    assert 'celda-persona' in html and 'btn-icono' in html and 'tabla-pie' in html


# ── Barra de título y botón principal ───────────────────────────────────
def test_el_boton_principal_y_la_barra_de_titulo(css):
    assert '.btn-primary,\n.btn-success {' in css
    assert 'background: var(--bg-elevated) !important;' in css
    assert '.btn-primary > i:first-child' in css and 'border-radius: 50%;' in css
    assert '.btn-sm.btn-primary > i:first-child' in css
    assert '.page-toolbar h2 > i { display: none; }' in css


def test_los_listados_llevan_titulo_y_subtitulo(c_admin, c_inst):
    html = texto(c_admin.get('/admin/usuarios'))
    assert 'page-titulo' in html and '>Usuarios<' in html and 'cuentas registradas' in html
    html = texto(c_admin.get('/admin/fichas'))
    assert 'page-titulo' in html and ('ficha registrada' in html or 'fichas registradas' in html)
    html = texto(c_inst.get('/instructor/aprendices'))
    assert 'page-titulo' in html and 'a tu cargo' in html


# ── Portal de acceso ────────────────────────────────────────────────────
def test_el_portal_de_acceso(anonimo, css):
    html = texto(anonimo.get('/login'))
    assert html.count('class="perfil') >= 3
    assert all(f'value="{p}"' in html for p in ('aprendiz', 'instructor', 'admin'))
    assert 'Oriente de Vélez' in html
    assert 'name="correo"' in html and 'name="password"' in html and 'csrf_token' in html
    assert '/registro' in html
    assert 'portal-intro' in html and 'portal-acceso' in html
    assert html.count('perfil-desc') == 3 and 'perfil-flecha' in html
    assert '.portal-hero {' in css and 'grid-template-columns' in css
    assert 'max-height: 760px' in css and 'max-height: 660px' in css


# ── Panel móvil ─────────────────────────────────────────────────────────
def test_el_panel_lateral_deslizante(c_ap, css):
    html = texto(c_ap.get('/aprendiz/dashboard'))
    assert 'lateral-movil' in html and 'panelAbrir' in html and 'panelFondo' in html
    desde = html.index('lateral-movil')
    panel = html[desde:html.index('</aside>', desde)]
    fija = html[html.index('lateral-fija'):desde]
    assert panel.count('lateral-item') == fija.count('lateral-item') > 0
    assert 'transform: translateX(-100%)' in css and '.lateral-movil.abierto' in css
    assert '.lateral-movil, .panel-fondo, .panel-abrir { display: none !important; }' in css
    assert 'dock' not in css and 'dock' not in html


# ── Sistema visual ──────────────────────────────────────────────────────
def test_fondo_con_desenfoque_y_superficies_translucidas(css):
    assert 'backdrop-filter' in css
    assert '--velo-bloque:' in css and '--desenfoque:    blur(' in css
    assert css.count('var(--desenfoque)') >= 12
    assert 'backdrop-filter: none !important' not in css
    assert '--velo-barra:    color-mix(in srgb, var(--bg-lateral) 55%' in css
    assert '.form-control,\n.form-select {' in css and '--input-bg) 70%, transparent' in css
    assert '.bg-dark,' in css and 'background-color: var(--velo-elevado) !important' in css


def test_paleta_del_rediseno_verde(css):
    assert '--bg-base:       #050a08' in css and '--bg-surface:    #0c1512' in css
    assert '--bg-lateral:    #091010' in css
    assert '--acc:        #3ee0a0' in css
    assert 'rgba(37, 201, 141, .14)' in css and 'rgba(45, 140, 255, .08)' in css
    assert 'rgba(240, 169, 59, .07)' not in css
    assert '.seccion > div:not(.seccion-acciones) { flex: 1 1 18rem' in css


def test_no_quedan_superficies_de_paletas_anteriores(css):
    for viejo in ('rgba(12, 12, 12', 'rgba(10, 10, 10', 'rgba(16, 20, 25', '#0f1623'):
        assert viejo not in css


def test_los_menus_desplegables_siguen_el_sistema(css):
    assert '.dropdown-menu {' in css and 'var(--velo-elevado) !important' in css
