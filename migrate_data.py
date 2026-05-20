import os
# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.orm import sessionmaker
from app import create_app, db
from app.models.rol import Rol
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.models.instructor import Instructor
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_instructor import CursoInstructor
from app.models.curso_aprendiz import CursoAprendiz
from app.models.usuario_rol import UsuarioRol
from app.models.evidencia import Evidencia
from app.models.historial_cambios import HistorialCambios
from app.models.notificacion import Notificacion
from app.models.progreso_aprendiz import ProgresoAprendiz

def migrate():
    # 1. Configurar app de Flask y base de datos PostgreSQL
    app = create_app()
    pg_uri = app.config['SQLALCHEMY_DATABASE_URI']
    
    # 2. Configurar motor SQLite (origen)
    sqlite_uri = 'sqlite:///instance/flaskdb.sqlite'
    sqlite_engine = create_engine(sqlite_uri)
    SQLiteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SQLiteSession()

    # 3. Orden de migración para respetar llaves foráneas
    models = [
        Rol,
        Empresa,
        Usuario,
        Instructor,
        Aprendiz,
        Curso,
        CursoInstructor,
        CursoAprendiz,
        UsuarioRol,
        Evidencia,
        HistorialCambios,
        Notificacion,
        ProgresoAprendiz
    ]

    print("Iniciando migración de datos...")

    with app.app_context():
        # Asegurar que las tablas existan en Postgres
        db.create_all()
        
        for model in models:
            table_name = model.__tablename__
            print(f"Migrando tabla: {table_name}...", end=" ")
            
            # Obtener todos los registros de SQLite
            items = sqlite_session.query(model).all()
            
            if not items:
                print("0 registros (saltando).")
                continue
            
            # Limpiar tabla en Postgres por si acaso (opcional)
            # db.session.query(model).delete()
            
            # Copiar cada registro a la sesión de Postgres
            for item in items:
                # Expunge from sqlite session to avoid conflicts
                sqlite_session.expunge(item)
                # Merge into postgres session (handles identity if already exists)
                db.session.merge(item)
            
            try:
                db.session.commit()
                print(f"{len(items)} registros migrados.")
            except Exception as e:
                db.session.rollback()
                print(f"ERROR: {e}")

        # 4. Reiniciar secuencias en PostgreSQL
        print("\nReiniciando secuencias de PostgreSQL...")
        for model in models:
            table_name = model.__tablename__
            # Obtener el nombre de la columna llave primaria
            pk_column = model.__mapper__.primary_key[0].name
            
            # Comando para reiniciar el contador de la secuencia (Postgres específico)
            sql = f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_column}'), COALESCE(MAX({pk_column}), 1)) FROM {table_name};"
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"No se pudo reiniciar secuencia para {table_name}: {e}")

    sqlite_session.close()
    print("\nMigración completada exitosamente.")

if __name__ == "__main__":
    migrate()
