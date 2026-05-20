# MÓDULO DE FICHAS - DOCUMENTACIÓN DE IMPLEMENTACIÓN

## 📋 RESUMEN EJECUTIVO

Se ha implementado exitosamente un módulo completo de gestión de fichas (cursos) para la plataforma Flask de SENA Prácticas. El módulo incluye:

- **Dashboard mejorado para Instructor**: Visión general de fichas, aprendices y progreso
- **Gestión de fichas para Instructor**: Listar, buscar y ver detalles de sus fichas asignadas
- **Administración completa de fichas para Admin**: CRUD completo con asignación de instructores
- **Barra de progreso visual**: Para que aprendices vean su avance

## 🎯 FUNCIONALIDADES IMPLEMENTADAS

### 1. DASHBOARD INSTRUCTOR MEJORADO
**Ubicación:** `/instructor/dashboard`
**Archivo:** `app/routes/instructor.py` + `app/templates/instructor/dashboard.html`

#### Cambios:
- Tarjeta de "Progreso General" con barra visual
- Tabla de "Mis Fichas/Cursos Asignados" con:
  - Nombre de ficha
  - Total de aprendices
  - Evidencias pendientes
  - Botón "Ver Detalle"
- Acceso rápido a "Gestionar Fichas" en acciones rápidas

#### Datos mostrados:
```python
fichas_data = [
    {
        'curso': curso_obj,
        'aprendices_count': int,
        'evidencias_pendientes': int
    },
    ...
]
```

---

### 2. LISTADO DE FICHAS DEL INSTRUCTOR
**Ubicación:** `/instructor/fichas`
**Archivo:** `app/routes/instructor.py:fichas()` + `app/templates/instructor/fichas/index.html`

#### Funcionalidades:
- Listar todas las fichas asignadas al instructor
- Búsqueda por nombre de ficha
- Tabla con estadísticas por ficha
- Botón "Ver Detalle" para cada ficha

#### Respuesta:
```python
@bp.route('/fichas')
def fichas():
    """GET /instructor/fichas"""
    fichas_data = [
        {
            'curso': Curso,
            'aprendices_count': int,
            'evidencias_pendientes': int
        }
    ]
```

---

### 3. DETALLE DE FICHA DEL INSTRUCTOR
**Ubicación:** `/instructor/fichas/<id_curso>/detalle`
**Archivo:** `app/routes/instructor.py:ficha_detalle()` + `app/templates/instructor/fichas/detalle.html`

#### Componentes:
1. **Información de la Ficha**
   - Nombre, código, fechas inicio/fin
   - Estadísticas: total aprendices, evidencias pendientes

2. **Tabla de Aprendices**
   - Nombre, empresa, horas cumplidas/requeridas
   - Barra de progreso individual (%)
   - Estado de práctica (En proceso/Completado)

3. **Tabla de Evidencias**
   - Aprendiz, tipo (archivo/enlace/texto)
   - Estado (Entregada/Aprobada/No Aprobada)
   - Fecha, botón revisar

#### Respuesta:
```python
@bp.route('/fichas/<int:id_curso>/detalle')
def ficha_detalle(id_curso):
    """GET /instructor/fichas/<id>/detalle"""
    aprendices_data = [
        {
            'aprendiz': Aprendiz,
            'progreso': float,  # %
            'horas_cumplidas': int,
            'horas_requeridas': int,
            'evidencias': [Evidencia]
        }
    ]
```

---

### 4. GESTIÓN DE FICHAS EN ADMIN
**Ubicación:** `/admin/fichas`
**Archivos:** `app/routes/admin.py` + `app/templates/admin/fichas/lista.html`

#### Funcionalidades CRUD:

#### 4.1 LISTAR FICHAS
```python
@bp.route('/admin/fichas')
def fichas():
    """GET /admin/fichas?q=<busqueda>"""
```

Características:
- Búsqueda por nombre
- Tabla con: Nombre | Instructores | Aprendices | Código | Acciones
- Botones: Editar, Asignar Instructor, Eliminar

---

#### 4.2 CREAR FICHA
```python
@bp.route('/admin/fichas/crear', methods=['POST'])
def crear_ficha():
    """POST /admin/fichas/crear"""
```

Parámetros:
- `nombre` (requerido, único)
- `ficha` (código opcional)
- `fecha_inicio` (opcional)
- `fecha_fin` (opcional)

Validaciones:
- Nombre no vacío
- Nombre único en BD
- Auditoría en historial

---

#### 4.3 EDITAR FICHA
```python
@bp.route('/admin/fichas/<int:id_curso>/editar', methods=['POST'])
def editar_ficha(id_curso):
    """POST /admin/fichas/<id>/editar"""
```

Parámetros: mismo que crear

Validaciones:
- Nombre único (si cambia)
- Auditoría de cambios

---

#### 4.4 ELIMINAR FICHA
```python
@bp.route('/admin/fichas/<int:id_curso>/eliminar', methods=['POST'])
def eliminar_ficha(id_curso):
    """POST /admin/fichas/<id>/eliminar"""
```

Validaciones:
- No puede eliminar si tiene aprendices asignados
- Confirmación requerida
- Auditoría de eliminación

---

#### 4.5 ASIGNAR INSTRUCTOR A FICHA
```python
@bp.route('/admin/fichas/<int:id_curso>/asignar-instructor', methods=['POST'])
def asignar_instructor_ficha(id_curso):
    """POST /admin/fichas/<id>/asignar-instructor"""
```

Parámetros:
- `id_instructor` (requerido)

Validaciones:
- Instructor existe
- No está ya asignado
- Solo instructores activos

Auditoría:
- Registra instructor asignado a ficha

---

#### 4.6 DESASIGNAR INSTRUCTOR
```python
@bp.route('/admin/fichas/<int:id_curso>/desasignar-instructor/<int:id_instructor>', methods=['POST'])
def desasignar_instructor_ficha(id_curso, id_instructor):
    """POST /admin/fichas/<id>/desasignar-instructor/<id_inst>"""
```

Validaciones:
- Asignación existe

---

### 5. BARRA DE PROGRESO PARA APRENDIZ
**Ubicación:** `/aprendiz/evidencias/subir`
**Archivo:** `app/routes/aprendiz.py:evidencias_subir()` + `app/templates/aprendiz/evidencias_subir.html`

#### Cambios:
- Cálculo de progreso: `(horas_cumplidas / horas_requeridas) * 100`
- Barra visual Bootstrap con porcentaje
- Mostrar: "X/Y horas"
- Texto motivacional

#### Parámetro a template:
```python
progreso_pct = round((ap.horas_cumplidas or 0) / ap.horas_requeridas * 100, 1)
return render_template('aprendiz/evidencias_subir.html', 
                      aprendiz=ap, 
                      progreso_pct=progreso_pct)
```

---

## 📁 ARCHIVOS MODIFICADOS/CREADOS

### Modificados:
1. `app/routes/instructor.py` (+134 líneas)
   - dashboard()
   - fichas() [NUEVA]
   - ficha_detalle() [NUEVA]

2. `app/routes/admin.py` (+209 líneas)
   - Imports de Curso, CursoInstructor, CursoAprendiz
   - fichas() [NUEVA]
   - crear_ficha() [NUEVA]
   - editar_ficha() [NUEVA]
   - eliminar_ficha() [NUEVA]
   - asignar_instructor_ficha() [NUEVA]
   - desasignar_instructor_ficha() [NUEVA]

3. `app/routes/aprendiz.py` (+20 líneas)
   - evidencias_subir(): Agregó cálculo progreso_pct

4. `app/templates/instructor/dashboard.html` (+81 líneas)
   - Tabla de fichas
   - Tarjeta progreso general
   - Botón gestionar fichas

5. `app/templates/aprendiz/evidencias_subir.html` (+30 líneas)
   - Card progreso personal
   - Barra Bootstrap

### Creados:
1. `app/templates/instructor/fichas/index.html` (86 líneas)
   - Búsqueda
   - Tabla fichas

2. `app/templates/instructor/fichas/detalle.html` (200 líneas)
   - Información ficha
   - Tabla aprendices con progreso
   - Tabla evidencias

3. `app/templates/admin/fichas/lista.html` (283 líneas)
   - Búsqueda
   - Tabla CRUD
   - 6 Modales (crear, editar x fichas, asignar, eliminar)

---

## 🔐 SEGURIDAD Y VALIDACIONES

### Permisos:
- Instructor: Solo ve sus fichas, acceso denegado a otras
- Admin: Acceso total a todas las fichas
- Aprendiz: Solo ve su progreso en subida de evidencias

### Validaciones de Entrada:
- Nombre no vacío
- Nombre único en BD
- IDs válidos (get_or_404)
- Instructor existe y activo
- No duplicar asignaciones

### Auditoría:
- Todas las operaciones se registran en `HistorialCambios`
- Usuario, acción, módulo, descripción

---

## 🧪 TESTING

Para probar manualmente:

### Instructor:
1. Login como instructor
2. Dashboard: Ver tabla fichas + progreso general
3. `/instructor/fichas`: Buscar fichas
4. `/instructor/fichas/<id>/detalle`: Ver aprendices + evidencias

### Admin:
1. Login como admin
2. `/admin/fichas`: Ver todas las fichas
3. Crear ficha: Modal "Nueva Ficha"
4. Editar ficha: Click botón "Editar"
5. Asignar instructor: Click "Asignar Instructor"
   - Dropdown instructores
   - Lista asignados con botón remover
6. Eliminar: Click "Eliminar" (solo si no hay aprendices)

### Aprendiz:
1. Login como aprendiz
2. `/aprendiz/evidencias/subir`: Ver barra progreso
3. Comprobar que muestra X/Y horas

---

## 📊 ESTADÍSTICAS

| Métrica | Valor |
|---------|-------|
| Rutas nuevas | 8 |
| Rutas modificadas | 3 |
| Templates nuevos | 3 |
| Templates mejorados | 2 |
| Líneas código | 1003 |
| Modales | 6 |
| Barras progreso | 2 |

---

## 🚀 PRÓXIMAS MEJORAS (OPCIONALES)

- [ ] Gráficos de progreso por ficha
- [ ] Exportar fichas a Excel
- [ ] Filtrado por estado en fichas
- [ ] Notificaciones por evidencias vencidas
- [ ] Asignación masiva de instructores
- [ ] Reporte de fichas por instructor

---

## 📝 NOTAS

- ✅ Sin cambios en BD (usa tabla Curso existente)
- ✅ Compatible con código existente
- ✅ Mismo estilo UI del proyecto
- ✅ Auditoría integrada
- ✅ Commit: 25a58ff

