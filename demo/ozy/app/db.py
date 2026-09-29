"""Conexión a la base propia de Ozy (ozy-mongodb)."""
from pymongo import MongoClient

from app.config import MONGODB_URL

database = MongoClient(MONGODB_URL).chat_ozy
