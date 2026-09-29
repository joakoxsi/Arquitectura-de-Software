"""Configuración de Ozy leída desde variables de entorno."""
import os

MONGODB_URL = os.environ["MONGODB_URL"]
USERS_URL = os.environ.get("USERS_URL", "http://users:8000")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
