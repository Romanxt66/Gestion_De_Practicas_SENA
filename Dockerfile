# Usa una imagen base de Python oficial
FROM python:3.10-slim

# Establece el directorio de trabajo en /app
WORKDIR /app

# Instala dependencias del sistema necesarias si es que hacen falta
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Copia el archivo de dependencias
COPY requirements.txt .

# Instala las dependencias necesarias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación
COPY . .

# Expone el puerto 5001, que es el que usa la app en run.py
EXPOSE 5001

# Comando por defecto para iniciar la aplicación
CMD ["python", "run.py"]
