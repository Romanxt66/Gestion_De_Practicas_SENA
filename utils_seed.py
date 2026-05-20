import sys
import os
from app import create_app, db
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.models.usuario_rol import UsuarioRol
from werkzeug.security import generate_password_hash, check_password_hash

def seed_data():
    """Crea los roles básicos y un usuario superusuario si la base de datos está vacía."""
    print("Iniciando Seed...")
    
    # 1. Crear roles
    roles = ['aprendiz', 'instructor', 'superusuario']
    for r in roles:
         if not Rol.query.filter_by(nombre=r).first():
             db.session.add(Rol(nombre=r, descripcion=f'Rol de {r} en el sistema'))
             print(f"Rol '{r}' creado.")
    
    db.session.commit()

    # 2. Crear superusuario inicial
    correo_admin = os.getenv('ADMIN_EMAIL')
    admin_pass = os.getenv('ADMIN_PASSWORD')
    tipo_documento = os.getenv('ADMIN_TIPO_DOCUMENTO')
    numero_documento = os.getenv('ADMIN_NUMERO_DOCUMENTO')
    nombres = os.getenv('ADMIN_NOMBRES')
    apellidos = os.getenv('ADMIN_APELLIDOS')
    
    if not admin_pass:
        print("⚠️ ADVERTENCIA: La variable de entorno ADMIN_PASSWORD no está definida.")
        print("⚠️ Saltando la creación o sincronización del superusuario por seguridad.")
        return
        
    admin_user = Usuario.query.filter_by(correo=correo_admin).first()
    
    if not admin_user:
        admin_user = Usuario(
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            nombres=nombres,
            apellidos=apellidos,
            correo=correo_admin,
            password_hash=generate_password_hash(admin_pass),
            estado=True
        )
        db.session.add(admin_user)
        db.session.flush() # Para tener su ID disponible sin comitear
        
        # Asignar rol superusuario
        rol_super = Rol.query.filter_by(nombre='superusuario').first()
        if rol_super:
            db.session.add(UsuarioRol(id_usuario=admin_user.id_usuario, id_rol=rol_super.id_rol))
            print(f"Superusuario '{correo_admin}' creado correctamente.")
        
        db.session.commit()
    else:
        # Sincronizar contraseña con la variable de entorno
        if not check_password_hash(admin_user.password_hash, admin_pass):
            admin_user.password_hash = generate_password_hash(admin_pass)
            db.session.commit()
            print(f"Contraseña del superusuario '{correo_admin}' sincronizada con la variable de entorno.")
        else:
            print("El superusuario ya existe y su contraseña está sincronizada.")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
        seed_data()
    print("Seed finalizado.")
