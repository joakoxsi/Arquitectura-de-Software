FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Usuario sin privilegios: el namespace del curso aplica PodSecurity "restricted".
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin gateway
USER 10001

EXPOSE 8000
# Sin --reload en la imagen (Kubernetes); docker-compose lo agrega con `command:`.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
