"""Conexión a la base propia de Ozy (ozy-mongodb)."""
from pymongo import MongoClient

from app.config import MONGODB_URL

# Timeout corto: si Mongo no responde, la readiness probe debe fallar rápido
# en vez de colgarse los 30 s por defecto de pymongo.
database = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=2000).chat_ozy
