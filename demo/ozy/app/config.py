"""Configuración de Ozy leída desde variables de entorno."""
import os

MONGODB_URL = os.environ["MONGODB_URL"]
USERS_URL = os.environ.get("USERS_URL", "http://users:8000")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
# Cómo llega chat.message.created al read-model:
# - "true" (compose): Ozy consume del broker donde publica `messages`.
# - "false" (clúster del curso): el `messages` del curso no publica eventos, así que
#   Ozy lee los mensajes por la API pública (app/synchronizer.py); RABBITMQ_URL apunta
#   entonces al broker propio de Ozy y solo se usa para publicar sus eventos.
CONSUME_MESSAGE_EVENTS = os.environ.get("CONSUME_MESSAGE_EVENTS", "true").lower() == "true"
# Sin broker, Ozy lee los mensajes por la API pública de channels y messages.
CHANNELS_URL = os.environ.get("CHANNELS_URL")
MESSAGES_URL = os.environ.get("MESSAGES_URL")
MESSAGE_SYNC_INTERVAL = int(os.environ.get("MESSAGE_SYNC_INTERVAL", "10"))
# Nombre de la réplica que atiende (en Kubernetes, el nombre del pod).
INSTANCE = os.environ.get("POD_NAME") or os.environ.get("HOSTNAME", "local")
# Segundos que el arranque espera a MongoDB antes de rendirse (y que K8s reinicie).
STARTUP_DB_TIMEOUT = int(os.environ.get("STARTUP_DB_TIMEOUT", "60"))
