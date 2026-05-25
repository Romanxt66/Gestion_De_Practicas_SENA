# 📗 Manual de Usuario: Instructor

Bienvenido al manual de usuario para el rol de Instructor en el sistema de **Gestión de Prácticas SENA**. Como instructor, tu labor principal es realizar el seguimiento a los aprendices asignados a tus fichas y evaluar sus evidencias de práctica.

---

## 1. Acceso al Sistema
Ingresa al sistema utilizando tu correo electrónico y contraseña. Al iniciar sesión, el sistema te llevará automáticamente a tu panel de control (Dashboard).

---

## 2. Dashboard Principal (Panel de Control)
- **Ubicación:** `/instructor/dashboard`
- **¿Qué encontrarás aquí?**
  - **Progreso General:** Una tarjeta que muestra una barra de progreso general de todos tus aprendices, calculada automáticamente.
  - **Mis Fichas Asignadas:** Una tabla resumen con las fichas que tienes a cargo. En esta tabla podrás ver rápidamente la cantidad total de aprendices por ficha y si existen evidencias pendientes por revisar.
  - **Acciones Rápidas:** Botones de acceso directo para ir a la gestión detallada de tus fichas.

---

## 3. Gestión de Fichas
Para acceder al listado completo de tus fichas y buscar información específica.
- **Ubicación:** Menú lateral > `Gestión de Fichas` (o en la URL `/instructor/fichas`).

### 3.1. Buscar y Consultar
- Utiliza la barra de búsqueda para filtrar tus fichas por nombre o número.
- En la tabla de resultados, presiona el botón **"Ver Detalle"** en cualquier ficha para acceder a la información profunda de la misma.

---

## 4. Detalle de la Ficha
Una vez que ingresas al detalle de una ficha específica (`/instructor/fichas/<id>/detalle`), tendrás acceso a la información vital para tu labor de seguimiento.

### 4.1. Información General
En la parte superior verás los datos de la ficha: nombre, código, fechas de inicio y fin, total de aprendices y la cantidad de evidencias que están pendientes de revisión.

### 4.2. Tabla de Aprendices y Progreso
Esta sección te muestra el listado de aprendices matriculados en la ficha.
- Podrás ver el **nombre** del aprendiz y la **empresa** donde realiza su práctica.
- Se muestra un contador de **Horas cumplidas vs Horas requeridas**.
- **Barra de progreso individual (%):** Cada aprendiz tiene una barra visual que refleja su avance porcentual en la práctica.
- **Estado de práctica:** Te indicará si el aprendiz está "En proceso" o si ha "Completado" sus requisitos.

### 4.3. Revisión de Evidencias
Al final del detalle de la ficha encontrarás la **Tabla de Evidencias**.
- Aquí se listan las evidencias enviadas por los aprendices (ya sean archivos adjuntos, enlaces o textos).
- Podrás ver el estado actual: *Entregada, Aprobada, No Aprobada*.
- Utiliza los botones de acción para **revisar** las evidencias, calificarlas y dejar retroalimentación al aprendiz.

> [!TIP]
> Te recomendamos revisar periódicamente el indicador de "Evidencias Pendientes" en tu Dashboard para mantener al día la retroalimentación de tus aprendices.
