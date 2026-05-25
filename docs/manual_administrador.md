# 📘 Manual de Usuario: Administrador (Superusuario)

Bienvenido al manual de usuario para el rol de Administrador en el sistema de **Gestión de Prácticas SENA**. Como administrador, tienes control total sobre la configuración, gestión de usuarios y administración de las fichas de formación.

---

## 1. Acceso al Sistema
Para ingresar, utiliza tus credenciales (correo electrónico y contraseña) en la pantalla de inicio de sesión. Una vez autenticado, serás redirigido al panel de administración principal.

---

## 2. Gestión de Fichas (Cursos)
El módulo de fichas te permite administrar todos los programas de formación y asignar instructores.

### 2.1. Listar y Buscar Fichas
- **Ubicación:** Menú lateral > `Gestión de Fichas` (o en la URL `/admin/fichas`).
- **Funcionalidad:** En esta vista encontrarás una tabla con todas las fichas registradas.
- **Búsqueda:** Utiliza la barra de búsqueda en la parte superior para filtrar fichas por su nombre o código.

### 2.2. Crear una Nueva Ficha
1. Haz clic en el botón **"Nueva Ficha"**.
2. Completa los campos en la ventana emergente (modal):
   - **Nombre:** (Requerido) Nombre del programa de formación.
   - **Código:** (Opcional) Número o identificador de la ficha.
   - **Fecha Inicio / Fin:** (Opcionales) Fechas de duración del programa.
3. Haz clic en guardar. El sistema validará que el nombre no esté duplicado.

### 2.3. Editar Ficha
1. En la tabla de fichas, ubica la ficha que deseas modificar.
2. Haz clic en el botón **"Editar"**.
3. Actualiza la información necesaria y guarda los cambios.

### 2.4. Eliminar Ficha
1. Haz clic en el botón **"Eliminar"** en la fila de la ficha correspondiente.
2. Confirma la acción.
> [!WARNING]
> **Importante:** Solo podrás eliminar una ficha si **no tiene aprendices asignados**. Si tiene aprendices, primero debes reasignarlos o eliminarlos.

---

## 3. Asignación de Instructores
Puedes asignar uno o varios instructores a una ficha para que realicen el seguimiento de los aprendices.

### 3.1. Asignar un Instructor a una Ficha
1. En la tabla de fichas, haz clic en **"Asignar Instructor"**.
2. En la ventana emergente, selecciona el instructor desde el menú desplegable.
3. Haz clic en confirmar.

### 3.2. Desasignar un Instructor
1. En el mismo panel de "Asignar Instructor", verás la lista de instructores que ya están a cargo de esa ficha.
2. Haz clic en el botón **"Remover"** junto al nombre del instructor que deseas desvincular.

---

## 4. Auditoría e Historial de Cambios
Todas las acciones críticas realizadas en el sistema (creación, edición, eliminación y asignaciones) quedan registradas para propósitos de auditoría.
- **Ubicación:** `/admin/historial`
- En esta sección puedes consultar qué usuario realizó cada cambio, en qué módulo, la fecha y la descripción exacta de la acción.

---
> [!TIP]
> Recuerda mantener siempre actualizados los datos de los instructores y las fichas para asegurar un correcto funcionamiento del sistema de seguimiento de prácticas.
