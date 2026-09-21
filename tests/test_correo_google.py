"""Servicio de correo (SMTP / Gmail), cifrado y flujo OAuth de Google, y las
rutas de /cuenta. Nada sale a la red: los transportes se sustituyen."""
import base64
import io
import json
import urllib.error
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app import db
from app.models.cuenta_google import CuentaGoogle
from app.models.usuario import Usuario
from app.servicios import correo as svc
from app.servicios import google_oauth
from conftest import cliente_de, crear_usuario, texto, token


@pytest.fixture
def usuarios(app):
    with app.app_context():
        ins = crear_usuario('instructor', nombres='Ines', apellidos='Instructora')
        ap = crear_usuario('aprendiz', nombres='Alma', apellidos='Aprendiz')
        return SimpleNamespace(ins=ins, ap=ap)


def obtener(app, ids):
    return db.session.get(Usuario, ids.id_usuario)


@pytest.fixture
def con_google(app, monkeypatch):
    """Credenciales de Google cargadas en la configuración."""
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', 'demo.apps.googleusercontent.com')
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_SECRET', 'secreto-demo')
    monkeypatch.setitem(app.config, 'GOOGLE_REDIRECT_URI', 'https://sena.example/cuenta/google/callback')


# ════════════════════════════════════════════════════════════════════════
# Mensaje y transportes
# ════════════════════════════════════════════════════════════════════════
def test_el_mensaje_lleva_las_cabeceras_de_entregabilidad():
    m = svc._construir_mensaje('notif@sena.test', 'SENA Prácticas', 'dest@x.co', 'Asunto',
                               'texto plano', '<p>html</p>', responder_a='alma@x.co')
    assert 'SENA Prácticas' in m['From'] and 'notif@sena.test' in m['From']
    assert m['To'] == 'dest@x.co' and m['Subject'] == 'Asunto'
    assert m['Reply-To'] == 'alma@x.co'
    assert m['Auto-Submitted'] == 'auto-generated'
    assert m.is_multipart()


def test_el_mensaje_sin_html_no_es_multiparte_ni_lleva_respuesta():
    m = svc._construir_mensaje('a@x.co', 'N', 'b@x.co', 'S', 'solo texto', None)
    assert not m.is_multipart() and m['Reply-To'] is None


def test_smtp_con_starttls(monkeypatch):
    llamadas = []

    class FalsoSMTP:
        def __init__(self, servidor, puerto, timeout=None):
            llamadas.append(('conectar', servidor, puerto))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            llamadas.append('starttls')

        def login(self, u, p):
            llamadas.append(('login', u, p))

        def send_message(self, m):
            llamadas.append('enviar')

    monkeypatch.setattr(svc.smtplib, 'SMTP', FalsoSMTP)
    svc._enviar_smtp({'ssl': False, 'servidor': 'smtp.x', 'puerto': 587, 'timeout': 5,
                      'usuario': 'u', 'password': 'p'}, object())
    assert llamadas == [('conectar', 'smtp.x', 587), 'starttls', ('login', 'u', 'p'), 'enviar']


def test_smtp_con_ssl(monkeypatch):
    llamadas = []

    class FalsoSSL:
        def __init__(self, servidor, puerto, timeout=None):
            llamadas.append(('ssl', servidor, puerto))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            llamadas.append('login')

        def send_message(self, m):
            llamadas.append('enviar')

    monkeypatch.setattr(svc.smtplib, 'SMTP_SSL', FalsoSSL)
    svc._enviar_smtp({'ssl': True, 'servidor': 'smtp.x', 'puerto': 465, 'timeout': 5,
                      'usuario': 'u', 'password': 'p'}, object())
    assert llamadas == [('ssl', 'smtp.x', 465), 'login', 'enviar']


def test_la_configuracion_smtp_sale_de_la_app(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_SERVER', 'smtp.prueba')
    monkeypatch.setitem(app.config, 'MAIL_PORT', 2525)
    with app.app_context():
        cfg = svc._config_smtp()
    assert cfg['servidor'] == 'smtp.prueba' and cfg['puerto'] == 2525


# ════════════════════════════════════════════════════════════════════════
# enviar_ahora (confirmaciones de correo)
# ════════════════════════════════════════════════════════════════════════
def test_enviar_ahora_sin_credenciales_devuelve_false(app):
    with app.app_context():
        assert app.enviar_ahora_real('x@y.co', 'a', 'b') is False


def test_enviar_ahora_sin_destinatario_devuelve_false(app):
    with app.app_context():
        assert app.enviar_ahora_real('', 'a', 'b') is False


def test_enviar_ahora_con_credenciales_envia_por_smtp(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 'clave')
    enviados = []
    monkeypatch.setattr(svc, '_enviar_smtp', lambda cfg, m: enviados.append(m))
    with app.app_context():
        assert app.enviar_ahora_real('x@y.co', 'Asunto', 'texto', '<p>h</p>') is True
    assert enviados[0]['To'] == 'x@y.co' and enviados[0]['Auto-Submitted'] == 'auto-generated'


def test_enviar_ahora_dice_false_si_el_servidor_falla(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 'clave')

    def falla(cfg, m):
        raise OSError('sin red')

    monkeypatch.setattr(svc, '_enviar_smtp', falla)
    with app.app_context():
        assert app.enviar_ahora_real('x@y.co', 'a', 'b') is False


# ════════════════════════════════════════════════════════════════════════
# Avisos del sistema (se encolan, sin tocar la red)
# ════════════════════════════════════════════════════════════════════════
def test_aviso_de_evidencia_subida_va_al_instructor(app, usuarios, avisos):
    with app.app_context(), app.test_request_context():
        svc.avisar_evidencia_subida(obtener(app, usuarios.ins), obtener(app, usuarios.ap),
                                    'Ficha Demo', 'archivo')
    a, = avisos
    assert a['destinatario'] == usuarios.ins.correo
    assert 'Alma Aprendiz' in a['asunto'] and 'Ficha Demo' in a['asunto']
    assert 'archivo' in a['texto'] and a['responder_a'] == usuarios.ap.correo


def test_aviso_de_evidencia_calificada_va_al_aprendiz(app, usuarios, avisos):
    with app.app_context(), app.test_request_context():
        svc.avisar_evidencia_calificada(obtener(app, usuarios.ap), obtener(app, usuarios.ins),
                                        'Aprobada', 'Buen trabajo', None)
    a, = avisos
    assert a['destinatario'] == usuarios.ap.correo
    assert 'Aprobada' in a['asunto'] and 'Buen trabajo' in a['texto']
    assert 'Buen trabajo' in a['html'] and a['responder_a'] == usuarios.ins.correo


def test_aviso_calificada_sin_observaciones_no_las_menciona(app, usuarios, avisos):
    with app.app_context(), app.test_request_context():
        svc.avisar_evidencia_calificada(obtener(app, usuarios.ap), obtener(app, usuarios.ins),
                                        'No Aprobada', '', None)
    assert 'Observaciones' not in avisos[0]['texto'] and 'Observaciones' not in avisos[0]['html']


def test_sin_cuenta_de_google_el_remitente_es_el_institucional(app, usuarios, avisos, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    with app.app_context(), app.test_request_context():
        svc.avisar_evidencia_subida(obtener(app, usuarios.ins), obtener(app, usuarios.ap), 'F', 'texto')
    assert avisos[0]['refresh_token'] is None
    assert avisos[0]['remitente'] == 'notif@sena.test'
    assert avisos[0]['remitente_nombre'] == 'SENA Prácticas'


def test_con_cuenta_vinculada_el_correo_sale_a_nombre_del_usuario(app, usuarios, avisos, con_google):
    with app.app_context(), app.test_request_context():
        db.session.add(CuentaGoogle(id_usuario=usuarios.ap.id_usuario, correo_google='alma@gmail.com',
                                    refresh_token=google_oauth.cifrar('token-demo')))
        db.session.commit()
        svc.avisar_evidencia_subida(obtener(app, usuarios.ins), obtener(app, usuarios.ap), 'F', 'texto')
    assert avisos[0]['remitente'] == 'alma@gmail.com'
    assert avisos[0]['refresh_token'] is not None and 'Alma Aprendiz' in avisos[0]['remitente_nombre']


def test_enviar_sin_destinatario_no_encola_nada(app, avisos):
    with app.app_context(), app.test_request_context():
        svc.enviar('', 'a', 'b')
    assert avisos == []


def test_la_maqueta_incluye_titulo_y_pie():
    html = svc.maqueta('Mi título', '<p>cuerpo</p>', 'pie de página')
    assert 'Mi título' in html and '<p>cuerpo</p>' in html and 'pie de página' in html


# ── Entrega en segundo plano ────────────────────────────────────────────
def datos_entrega(**extra):
    d = {'destinatario': 'dest@x.co', 'asunto': 'A', 'texto': 'T', 'html': '<p>h</p>',
         'refresh_token': None, 'remitente': 'notif@sena.test',
         'remitente_nombre': 'SENA Prácticas', 'responder_a': 'alma@x.co', 'id_cuenta': None}
    d.update(extra)
    return d


def test_entregar_sin_credenciales_no_intenta_enviar(app, monkeypatch):
    monkeypatch.setattr(svc, '_enviar_smtp',
                        lambda *a: pytest.fail('no debía intentar enviar por SMTP'))
    svc._entregar(app, datos_entrega())


def test_entregar_por_smtp_con_las_cabeceras_correctas(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 'x')
    capturados = []
    monkeypatch.setattr(svc, '_enviar_smtp', lambda cfg, m: capturados.append(m))
    svc._entregar(app, datos_entrega())
    m, = capturados
    assert 'SENA Prácticas' in m['From'] and m['Reply-To'] == 'alma@x.co'
    assert m['Auto-Submitted'] == 'auto-generated' and m.is_multipart()


def test_un_fallo_de_smtp_no_rompe_la_entrega(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 'x')
    monkeypatch.setattr(svc, '_enviar_smtp', lambda cfg, m: (_ for _ in ()).throw(OSError('caído')))
    svc._entregar(app, datos_entrega())


def test_entregar_por_gmail_si_hay_cuenta_vinculada(app, con_google, monkeypatch):
    enviados = []
    monkeypatch.setattr(google_oauth, 'enviar_gmail', lambda token, m: enviados.append((token, m)))
    monkeypatch.setattr(svc, '_enviar_smtp', lambda *a: pytest.fail('debía usar Gmail'))
    svc._entregar(app, datos_entrega(refresh_token='cifrado', remitente='alma@gmail.com'))
    (token_usado, m), = enviados
    assert token_usado == 'cifrado' and m['From'].endswith('<alma@gmail.com>')
    assert m['Reply-To'] == 'alma@gmail.com'


def test_si_gmail_falla_se_anota_el_error_y_se_usa_smtp(app, usuarios, con_google, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'notif@sena.test')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 'x')
    with app.app_context():
        cuenta = CuentaGoogle(id_usuario=usuarios.ap.id_usuario, correo_google='alma@gmail.com',
                              refresh_token=google_oauth.cifrar('t'))
        db.session.add(cuenta)
        db.session.commit()
        id_cuenta = cuenta.id_cuenta

    def falla(token, m):
        raise google_oauth.ErrorGoogle('token revocado')

    smtp = []
    monkeypatch.setattr(google_oauth, 'enviar_gmail', falla)
    monkeypatch.setattr(svc, '_enviar_smtp', lambda cfg, m: smtp.append(m))
    svc._entregar(app, datos_entrega(refresh_token='cifrado', remitente='alma@gmail.com',
                                     id_cuenta=id_cuenta))
    assert len(smtp) == 1
    with app.app_context():
        assert db.session.get(CuentaGoogle, id_cuenta).ultimo_error == 'token revocado'


# ════════════════════════════════════════════════════════════════════════
# google_oauth
# ════════════════════════════════════════════════════════════════════════
def test_el_refresh_token_se_guarda_cifrado_y_se_recupera(app):
    with app.app_context():
        cifrado = google_oauth.cifrar('1//refresh-de-prueba')
        assert '1//refresh-de-prueba' not in cifrado
        assert google_oauth.descifrar(cifrado) == '1//refresh-de-prueba'


def test_un_token_ilegible_da_un_error_claro(app):
    with app.app_context(), pytest.raises(google_oauth.ErrorGoogle, match='Vuelve a conectar'):
        google_oauth.descifrar('esto-no-esta-cifrado')


def test_cambiar_la_clave_de_cifrado_invalida_los_tokens(app, monkeypatch):
    with app.app_context():
        cifrado = google_oauth.cifrar('secreto')
        monkeypatch.setitem(app.config, 'TOKEN_ENCRYPTION_KEY', 'otra-clave-distinta')
        with pytest.raises(google_oauth.ErrorGoogle):
            google_oauth.descifrar(cifrado)
        assert google_oauth.descifrar(google_oauth.cifrar('nuevo')) == 'nuevo'


def test_esta_configurado_exige_id_y_secreto(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', '')
        monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_SECRET', '')
        assert google_oauth.esta_configurado() is False
        monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', 'id')
        assert google_oauth.esta_configurado() is False
        monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_SECRET', 'secreto')
        assert google_oauth.esta_configurado() is True


def test_la_url_de_autorizacion_pide_solo_enviar_y_refresh_token(app, con_google):
    with app.app_context():
        url = google_oauth.url_autorizacion('https://sena.example/cb', 'estado-123')
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == 'accounts.google.com'
    assert q['client_id'] == ['demo.apps.googleusercontent.com']
    assert q['redirect_uri'] == ['https://sena.example/cb'] and q['state'] == ['estado-123']
    assert q['access_type'] == ['offline'] and q['prompt'] == ['consent']
    assert 'gmail.send' in q['scope'][0] and 'gmail.readonly' not in q['scope'][0]


def test_canjear_codigo_devuelve_token_y_correo(app, con_google, monkeypatch):
    respuestas = iter([{'refresh_token': 'R', 'access_token': 'A', 'scope': 's1 s2'},
                       {'email': 'alma@gmail.com'}])
    monkeypatch.setattr(google_oauth, '_peticion', lambda *a, **k: next(respuestas))
    with app.app_context():
        r = google_oauth.canjear_codigo('codigo', 'https://sena.example/cb')
    assert r == {'refresh_token': 'R', 'correo': 'alma@gmail.com', 'scopes': 's1 s2'}


def test_canjear_codigo_sin_refresh_token_explica_como_revocar(app, con_google, monkeypatch):
    monkeypatch.setattr(google_oauth, '_peticion', lambda *a, **k: {'access_token': 'A'})
    with app.app_context(), pytest.raises(google_oauth.ErrorGoogle, match='permissions'):
        google_oauth.canjear_codigo('codigo', 'x')


def test_canjear_codigo_tolera_que_falle_la_consulta_del_correo(app, con_google, monkeypatch):
    def peticion(url, *a, **k):
        if url == google_oauth.USERINFO_URL:
            raise google_oauth.ErrorGoogle('sin acceso')
        return {'refresh_token': 'R', 'access_token': 'A'}

    monkeypatch.setattr(google_oauth, '_peticion', peticion)
    with app.app_context():
        assert google_oauth.canjear_codigo('c', 'x')['correo'] == ''


def test_access_token_desde_el_refresh_token(app, con_google, monkeypatch):
    pedidos = []
    monkeypatch.setattr(google_oauth, '_peticion',
                        lambda url, datos=None, **k: pedidos.append(datos) or {'access_token': 'NUEVO'})
    with app.app_context():
        assert google_oauth.access_token(google_oauth.cifrar('R')) == 'NUEVO'
    assert pedidos[0]['refresh_token'] == 'R' and pedidos[0]['grant_type'] == 'refresh_token'


def test_access_token_sin_respuesta_util(app, con_google, monkeypatch):
    monkeypatch.setattr(google_oauth, '_peticion', lambda *a, **k: {})
    with app.app_context(), pytest.raises(google_oauth.ErrorGoogle):
        google_oauth.access_token(google_oauth.cifrar('R'))


def test_revocar_no_falla_aunque_google_no_responda(app, monkeypatch):
    def falla(*a, **k):
        raise google_oauth.ErrorGoogle('caído')

    monkeypatch.setattr(google_oauth, '_peticion', falla)
    with app.app_context():
        google_oauth.revocar(google_oauth.cifrar('R'))


def test_enviar_gmail_manda_el_mensaje_codificado(app, con_google, monkeypatch):
    pedidos = []
    monkeypatch.setattr(google_oauth, 'access_token', lambda cifrado: 'TOKEN')
    monkeypatch.setattr(google_oauth, '_peticion',
                        lambda url, datos=None, cabeceras=None, **k: pedidos.append((url, datos, cabeceras)))
    mensaje = svc._construir_mensaje('a@x.co', 'N', 'b@x.co', 'Hola', 'cuerpo', None)
    with app.app_context():
        google_oauth.enviar_gmail('cifrado', mensaje)
    url, datos, cabeceras = pedidos[0]
    assert url == google_oauth.GMAIL_SEND_URL and cabeceras['Authorization'] == 'Bearer TOKEN'
    crudo = json.loads(datos)['raw']
    assert b'Subject: Hola' in base64.urlsafe_b64decode(crudo)


def test_los_errores_http_de_google_se_convierten_en_un_mensaje(monkeypatch):
    cuerpo = io.BytesIO(json.dumps({'error_description': 'código inválido'}).encode())

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError('u', 400, 'malo', {}, cuerpo)

    monkeypatch.setattr(google_oauth.urllib.request, 'urlopen', urlopen)
    with pytest.raises(google_oauth.ErrorGoogle, match='400.*código inválido'):
        google_oauth._peticion('https://google.example')


def test_un_error_de_red_se_convierte_en_un_mensaje(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.URLError('sin conexión')

    monkeypatch.setattr(google_oauth.urllib.request, 'urlopen', urlopen)
    with pytest.raises(google_oauth.ErrorGoogle, match='No se pudo contactar'):
        google_oauth._peticion('https://google.example')


# ════════════════════════════════════════════════════════════════════════
# Rutas de /cuenta
# ════════════════════════════════════════════════════════════════════════
def test_conexiones_es_visible_para_los_tres_roles(c_ap, c_inst, c_admin):
    for c in (c_ap, c_inst, c_admin):
        assert c.get('/cuenta/conexiones').status_code == 200


def test_conexiones_exige_sesion(anonimo):
    assert anonimo.get('/cuenta/conexiones').status_code == 302


def test_sin_credenciales_avisa_que_no_esta_disponible(app, c_ap, monkeypatch):
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', '')
    html = texto(c_ap.get('/cuenta/conexiones'))
    assert 'Todaví' in html or 'no ha cargado' in html


def test_conectar_sin_credenciales_no_falla(app, c_ap, monkeypatch):
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', '')
    r = c_ap.get('/cuenta/google/conectar', follow_redirects=True)
    assert r.status_code == 200 and 'no ha configurado' in texto(r)


def iniciar(cliente):
    """Empieza el flujo y devuelve el state firmado que viaja a Google."""
    r = cliente.get('/cuenta/google/conectar')
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers['Location']).query)
    return r.headers['Location'], q['state'][0]


def test_conectar_redirige_a_google_con_un_state_firmado(c_ap, con_google):
    ubicacion, state = iniciar(c_ap)
    assert ubicacion.startswith('https://accounts.google.com/')
    with c_ap.session_transaction() as s:
        assert s['oauth_google_state'] == state


def test_un_state_inventado_se_rechaza(c_ap):
    assert c_ap.get('/cuenta/google/callback?code=x&state=falsificado').status_code == 400


def test_el_callback_exige_sesion(anonimo):
    assert anonimo.get('/cuenta/google/callback?code=x&state=y').status_code == 302


def test_el_usuario_cancela_en_google(c_ap):
    r = c_ap.get('/cuenta/google/callback?error=access_denied', follow_redirects=True)
    assert 'Cancelaste' in texto(r)
    r = c_ap.get('/cuenta/google/callback?error=server_error', follow_redirects=True)
    assert 'server_error' in texto(r)


def test_el_state_de_otro_usuario_se_rechaza(app, datos, c_ap, con_google):
    _, state = iniciar(c_ap)
    otro = cliente_de(app, datos.ajeno_uid)
    with otro.session_transaction() as s:
        s['oauth_google_state'] = state
    assert otro.get(f'/cuenta/google/callback?code=x&state={state}').status_code == 400


def test_un_state_caducado_pide_reintentar(c_ap, con_google, monkeypatch):
    from app.routes import cuenta
    _, state = iniciar(c_ap)
    monkeypatch.setattr(cuenta, 'VIGENCIA_STATE', -1)
    r = c_ap.get(f'/cuenta/google/callback?code=x&state={state}', follow_redirects=True)
    assert 'caducó' in texto(r)


def test_el_callback_sin_codigo(c_ap, con_google):
    _, state = iniciar(c_ap)
    r = c_ap.get(f'/cuenta/google/callback?state={state}', follow_redirects=True)
    assert 'no devolvió el código' in texto(r)


def test_error_de_google_al_canjear_el_codigo(c_ap, con_google, monkeypatch):
    def falla(codigo, uri):
        raise google_oauth.ErrorGoogle('Google respondió 400.')

    monkeypatch.setattr(google_oauth, 'canjear_codigo', falla)
    _, state = iniciar(c_ap)
    r = c_ap.get(f'/cuenta/google/callback?code=x&state={state}', follow_redirects=True)
    assert 'Google respondió 400' in texto(r)


def test_conectar_guarda_la_cuenta_cifrada_y_reconectar_no_la_duplica(app, datos, c_ap, con_google,
                                                                     monkeypatch):
    monkeypatch.setattr(google_oauth, 'canjear_codigo',
                        lambda codigo, uri: {'refresh_token': '1//secreto', 'correo': 'alma@gmail.com',
                                             'scopes': 'gmail.send'})
    for _ in range(2):
        _, state = iniciar(c_ap)
        r = c_ap.get(f'/cuenta/google/callback?code=x&state={state}', follow_redirects=True)
        assert 'Cuenta de Google conectada: alma@gmail.com' in texto(r)
    with app.app_context():
        cuentas = CuentaGoogle.query.filter_by(id_usuario=datos.ap_id).all()
        assert len(cuentas) == 1
        assert cuentas[0].refresh_token != '1//secreto'
        assert google_oauth.descifrar(cuentas[0].refresh_token) == '1//secreto'
    assert 'alma@gmail.com' in texto(c_ap.get('/cuenta/conexiones'))


def test_desconectar_elimina_la_cuenta_y_revoca_el_permiso(app, datos, c_ap, con_google, monkeypatch):
    revocados = []
    monkeypatch.setattr(google_oauth, 'revocar', lambda cifrado: revocados.append(cifrado))
    with app.app_context():
        CuentaGoogle.query.filter_by(id_usuario=datos.ap_id).delete()
        db.session.add(CuentaGoogle(id_usuario=datos.ap_id, correo_google='alma@gmail.com',
                                    refresh_token=google_oauth.cifrar('t')))
        db.session.commit()
    r = c_ap.post('/cuenta/google/desconectar',
                  data={'csrf_token': token(c_ap, '/cuenta/conexiones')}, follow_redirects=True)
    assert 'desconectada' in texto(r) and len(revocados) == 1
    with app.app_context():
        assert CuentaGoogle.query.filter_by(id_usuario=datos.ap_id).first() is None


def test_desconectar_sin_cuenta_no_falla(app, datos, c_ap):
    with app.app_context():
        CuentaGoogle.query.filter_by(id_usuario=datos.ap_id).delete()
        db.session.commit()
    r = c_ap.post('/cuenta/google/desconectar',
                  data={'csrf_token': token(c_ap, '/aprendiz/informacion')}, follow_redirects=True)
    assert r.status_code == 200
