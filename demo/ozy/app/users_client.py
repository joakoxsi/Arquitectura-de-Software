"""Consulta opcional al servicio users para mostrar el nombre del autor."""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from app.config import USERS_URL

logger = logging.getLogger("ozy.users")


def get_display_name(author_id: str) -> str | None:
    """Devuelve None si users no responde: la traducción se entrega igual."""
    try:
        with urlopen(f"{USERS_URL}/api/v1/users/{quote(author_id, safe='')}",
                     timeout=2) as response:
            return json.load(response).get("display_name")
    except (HTTPError, URLError, TimeoutError, ValueError, AttributeError) as error:
        logger.warning("Could not fetch author %s from users: %s", author_id, error)
        return None
