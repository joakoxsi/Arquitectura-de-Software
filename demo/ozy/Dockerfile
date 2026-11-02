FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Los scripts viajan en la imagen para correr la prueba integrada y la carga
# como Jobs dentro del clúster, sin depender de otras imágenes.
COPY scripts ./scripts

# Usuario sin privilegios (Kubernetes lo exige con runAsNonRoot).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ozy
USER 10001

EXPOSE 8000
# Sin --reload: en producción un proceso por pod; la escala la da el HPA.
# En desarrollo, docker-compose sobrescribe este comando con --reload.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
