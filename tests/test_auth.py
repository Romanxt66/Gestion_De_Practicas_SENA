"""Login, perfiles, registro con confirmación de correo, CSRF y páginas legales."""
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app import db
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.models.verificacion_correo import VerificacionCorreo
from app.servicios import correo as serv_correo
from app.servicios import verificacion
from conftest import (CLAVE_ADMIN, CLAVE_APRENDIZ, CLAVE_INSTRUCTOR, crear_usuario,
                      enlace_de, texto, token, unico)


def entrar(cliente, correo, clave, perfil=None, **extra):
    datos = {'correo': correo, 'password': clave,
             'csrf_token': token(cliente, '/login'), **extra}
    if perfil:
        datos['perfil'] = perfil
    return cliente.post('/login', data=datos)


# ── Formulario de acceso ────────────────────────────────────────────────
def test_el_login_ofrece_los_tres_perfiles(anonimo):
    html = texto(anonimo.get('/login'))
    for perfil in ('aprendiz', 'instructor', 'admin'):
        assert f'value="{perfil}"' in html
    assert 'name="correo"' in html and 'csrf_token' in html
    assert 'data-perfil=' in html


def test_el_login_enlaza_a_las_paginas_legales(anonimo):
    html = texto(anonimo.get('/login'))
    assert '/privacidad' in html and '/terminos' in html


def test_post_sin_csrf_se_rechaza(anonimo, datos):
    r = anonimo.post('/login', data={'correo': datos.ap_correo, 'password': CLAVE_APRENDIZ,
                                     'perfil': 'aprendiz'})
    assert r.status_code == 400 and 'Sesión expirada' in texto(r)


# ── Login ───────────────────────────────────────────────────────────────
def test_aprendiz_entra_a_su_panel(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ, 'aprendiz')
    assert r.status_code == 302 and 'aprendiz' in r.headers['Location']
    assert anonimo.get('/aprendiz/dashboard').status_code == 200


def test_instructor_entra_a_su_panel(anonimo, datos):
    r = entrar(anonimo, datos.inst_correo, CLAVE_INSTRUCTOR, 'instructor')
    assert r.status_code == 302 and 'instructor' in r.headers['Location']
    assert anonimo.get('/instructor/dashboard').status_code == 200


def test_administrador_entra_eligiendo_administrador(anonimo, datos):
    r = entrar(anonimo, datos.admin_correo, CLAVE_ADMIN, 'admin')
    assert r.status_code == 302 and 'admin' in r.headers['Location']
    assert anonimo.get('/admin/dashboard').status_code == 200


def test_el_correo_no_distingue_mayusculas(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo.upper(), CLAVE_APRENDIZ, 'aprendiz')
    assert r.status_code == 302


def test_clave_incorrecta_da_mensaje_generico(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo, 'mala', 'aprendiz')
    assert 'Correo o contraseña incorrectos' in texto(r)


def test_correo_inexistente_da_el_mismo_mensaje(anonimo):
    r = entrar(anonimo, 'nadie@nada.com', 'lo-que-sea', 'aprendiz')
    assert 'Correo o contraseña incorrectos' in texto(r)


def test_campos_vacios(anonimo):
    r = anonimo.post('/login', data={'correo': '', 'password': '',
                                     'csrf_token': token(anonimo, '/login')})
    assert 'Ingresa tu correo y contraseña' in texto(r)


def test_cuenta_desactivada_no_entra(app, anonimo):
    with app.app_context():
        u = crear_usuario('aprendiz', clave='clave123')
        db.session.get(Usuario, u.id_usuario).estado = False
        db.session.commit()
    r = entrar(anonimo, u.correo, 'clave123', 'aprendiz')
    assert 'desactivada' in texto(r)
    with anonimo.session_transaction() as s:
        assert '_user_id' not in s


def test_aprendiz_no_entra_eligiendo_administrador(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ, 'admin')
    assert r.status_code == 200 and 'no es de tipo Administrador' in texto(r)
    with anonimo.session_transaction() as s:
        assert '_user_id' not in s


def test_aprendiz_no_entra_eligiendo_instructor_y_se_le_indica_su_perfil(anonimo, datos):
    html = texto(entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ, 'instructor'))
    assert 'no es de tipo Instructor' in html and 'Ingresa como Aprendiz' in html


def test_sin_elegir_perfil_no_deja_entrar(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ)
    assert 'Selecciona el tipo de cuenta' in texto(r)


def test_perfil_inventado_no_deja_entrar(anonimo, datos):
    r = entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ, 'root')
    assert 'Selecciona el tipo de cuenta' in texto(r)


def test_cuenta_sin_rol_recibe_aviso(app, anonimo):
    with app.app_context():
        u = Usuario(nombres='Sin', apellidos='Rol', correo=f'{unico()}@t.local',
                    password_hash=generate_password_hash('clave123'), estado=True)
        db.session.add(u)
        db.session.commit()
        correo = u.correo
    r = entrar(anonimo, correo, 'clave123', 'aprendiz')
    assert 'no tiene un rol asignado' in texto(r)


def test_logout_cierra_la_sesion(anonimo, datos):
    entrar(anonimo, datos.ap_correo, CLAVE_APRENDIZ, 'aprendiz')
    assert anonimo.get('/aprendiz/dashboard').status_code == 200
    assert anonimo.get('/logout').status_code == 302
    assert anonimo.get('/aprendiz/dashboard').status_code == 302


def test_logout_exige_sesion(anonimo):
    assert anonimo.get('/logout').status_code == 302
    assert '/login' in anonimo.get('/logout').headers['Location']


def test_la_raiz_con_sesion_lleva_al_panel_del_rol(c_admin, c_inst, c_ap):
    assert 'admin' in c_admin.get('/').headers['Location']
    assert 'instructor' in c_inst.get('/').headers['Location']
    assert 'aprendiz' in c_ap.get('/').headers['Location']


# ── Registro ────────────────────────────────────────────────────────────
def campos_registro(**cambios):
    campos = dict(tipo_documento='CC', numero_documento=unico('') + '1',
                  nombres='Nuevo', apellidos='Aprendiz', correo=f'{unico("n")}@test.com',
                  telefono='3001112233', password='clave123',
                  confirm_password='clave123', codigo_ficha='CI0001')
    campos.update(cambios)
    return campos


def registrar(cliente, **cambios):
    campos = campos_registro(**cambios)
    campos['csrf_token'] = token(cliente, '/registro')
    return campos, cliente.post('/registro', data=campos, follow_redirects=True)


def test_el_formulario_de_registro_tiene_todos_los_campos(anonimo):
    html = texto(anonimo.get('/registro'))
    for campo in ('nombres', 'apellidos', 'tipo_documento', 'numero_documento',
                  'correo', 'telefono', 'codigo_ficha', 'password', 'confirm_password'):
        assert f'name="{campo}"' in html


@pytest.mark.parametrize('cambios,mensaje', [
    ({'nombres': ''}, 'Completa todos los campos obligatorios'),
    ({'codigo_ficha': ''}, 'Completa todos los campos obligatorios'),
    ({'confirm_password': 'otra-clave'}, 'no coinciden'),
    ({'password': '123', 'confirm_password': '123'}, 'al menos 6'),
    ({'correo': 'no-es-correo'}, 'correo electrónico válido'),
    ({'correo': 'aprendiz.propio@test.local'}, 'Ya existe una cuenta con ese correo'),
])
def test_validaciones_del_registro(anonimo, cambios, mensaje):
    campos, r = registrar(anonimo, **cambios)
    assert mensaje in texto(r)
    with anonimo.application.app_context():
        assert VerificacionCorreo.query.filter_by(correo=campos['correo']).first() is None


def test_registro_con_documento_repetido(app, anonimo):
    documento = unico('') + '2'
    with app.app_context():
        crear_usuario('aprendiz', numero_documento=documento)
    _, r = registrar(anonimo, numero_documento=documento)
    assert 'número de documento' in texto(r)


def test_registro_deja_un_alta_en_espera_y_envia_el_correo(app, anonimo, correos):
    campos, r = registrar(anonimo)
    html = texto(r)
    assert 'Revisa tu' in html and campos['correo'] in html
    assert correos[-1]['para'] == campos['correo']
    assert 'Confirma tu correo' in correos[-1]['asunto']
    with app.app_context():
        assert Usuario.query.filter_by(correo=campos['correo']).first() is None
        assert VerificacionCorreo.query.filter_by(correo=campos['correo']).first()


def test_registrarse_dos_veces_no_duplica_el_alta_en_espera(app, anonimo, correos):
    campos, _ = registrar(anonimo)
    registrar(anonimo, correo=campos['correo'])
    with app.app_context():
        assert VerificacionCorreo.query.filter_by(correo=campos['correo']).count() == 1


def test_sin_confirmar_no_se_puede_iniciar_sesion(anonimo, correos):
    campos, _ = registrar(anonimo)
    r = entrar(anonimo, campos['correo'], 'clave123', 'aprendiz')
    assert r.status_code == 200 and 'Correo o contraseña incorrectos' in texto(r)


def test_confirmar_el_correo_crea_la_cuenta_matriculada(app, datos, anonimo, correos):
    campos, _ = registrar(anonimo)
    r = anonimo.get(enlace_de(correos), follow_redirects=True)
    assert 'Correo confirmado' in texto(r)
    with app.app_context():
        u = Usuario.query.filter_by(correo=campos['correo']).first()
        assert u is not None and u.aprendiz is not None
        assert u.aprendiz.ficha == 'CI0001'
        assert [c.id_curso for c in u.aprendiz.cursos] == [datos.id_curso]
        assert u.tipo_documento == 'CC' and u.telefono == '3001112233'
        assert VerificacionCorreo.query.filter_by(correo=campos['correo']).first() is None
    assert entrar(anonimo, campos['correo'], 'clave123', 'aprendiz').status_code == 302


def test_el_enlace_no_se_puede_reutilizar(anonimo, correos):
    registrar(anonimo)
    enlace = enlace_de(correos)
    anonimo.get(enlace)
    assert 'ya se usó' in texto(anonimo.get(enlace, follow_redirects=True))


def test_un_enlace_manipulado_se_rechaza(anonimo):
    r = anonimo.get('/verificar/esto-no-es-un-token', follow_redirects=True)
    assert 'no es válido' in texto(r)


def test_un_enlace_caducado_se_rechaza(anonimo, correos, monkeypatch):
    registrar(anonimo)
    monkeypatch.setattr(verificacion, 'HORAS_VALIDEZ', -1)
    r = anonimo.get(enlace_de(correos), follow_redirects=True)
    assert 'caducó' in texto(r)


def test_registro_con_ficha_inexistente_deja_al_aprendiz_en_espera(app, anonimo, correos):
    codigo = unico('ZZ-')
    campos, _ = registrar(anonimo, codigo_ficha=codigo)
    r = anonimo.get(enlace_de(correos), follow_redirects=True)
    assert 'todavía no está registrada' in texto(r)
    with app.app_context():
        u = Usuario.query.filter_by(correo=campos['correo']).first()
        assert u.aprendiz.ficha == codigo and u.aprendiz.cursos == []
        assert Notificacion.query.filter(Notificacion.mensaje.like(f'%{codigo}%')).count() >= 1


def test_si_no_sale_el_correo_no_queda_alta_a_medias(app, anonimo, monkeypatch):
    monkeypatch.setattr(serv_correo, 'enviar_ahora', lambda *a, **k: False)
    campos, r = registrar(anonimo)
    assert 'No pudimos enviar el correo' in texto(r)
    with app.app_context():
        assert VerificacionCorreo.query.filter_by(correo=campos['correo']).first() is None


def test_revisa_tu_correo_sin_registro_previo_redirige(anonimo):
    r = anonimo.get('/registro/revisa-tu-correo')
    assert r.status_code == 302 and '/registro' in r.headers['Location']


def test_confirmar_cuando_el_correo_ya_tiene_cuenta(app, anonimo, correos):
    campos, _ = registrar(anonimo)
    with app.app_context():
        crear_usuario('aprendiz', correo=campos['correo'])
    r = anonimo.get(enlace_de(correos), follow_redirects=True)
    assert 'Ya existe una cuenta con ese correo' in texto(r)


def test_limpiar_caducadas_borra_solo_las_vencidas(app):
    with app.app_context():
        vieja = VerificacionCorreo(correo=f'{unico()}@v.co', datos='{}',
                                   fecha_creacion=datetime.now(timezone.utc)
                                   - timedelta(hours=verificacion.HORAS_VALIDEZ + 5))
        reciente = VerificacionCorreo(correo=f'{unico()}@r.co', datos='{}')
        db.session.add_all([vieja, reciente])
        db.session.commit()
        ids = (vieja.id_verificacion, reciente.id_verificacion)
        assert verificacion.limpiar_caducadas() >= 1
        assert db.session.get(VerificacionCorreo, ids[0]) is None
        assert db.session.get(VerificacionCorreo, ids[1]) is not None


# ── CSRF ────────────────────────────────────────────────────────────────
def test_los_formularios_traen_token_csrf(c_admin):
    assert token(c_admin, '/admin/empresas') is not None


def test_post_sin_token_csrf_es_rechazado(c_admin):
    r = c_admin.post('/admin/empresas/crear', data={'nombre': 'Sin Token SA'})
    assert r.status_code == 400


def test_post_con_token_csrf_funciona(c_admin):
    nombre = f'Empresa {unico()}'
    r = c_admin.post('/admin/empresas/crear',
                     data={'nombre': nombre, 'csrf_token': token(c_admin, '/admin/empresas')},
                     follow_redirects=True)
    assert r.status_code == 200 and nombre in texto(r)


# ── Páginas legales ─────────────────────────────────────────────────────
def test_privacidad_es_publica_y_explica_el_alcance(anonimo):
    r = anonimo.get('/privacidad')
    html = texto(r)
    assert r.status_code == 200 and 'gmail.send' in html
    assert 'no puede leer el buzón' in html
    assert 'myaccount.google.com/permissions' in html


def test_terminos_es_publico(anonimo):
    r = anonimo.get('/terminos')
    assert r.status_code == 200 and 'Uso aceptable' in texto(r)
