"""Los microservicios se simulan con respx: interceptan las llamadas httpx del Gateway."""
import pytest
import respx
from fastapi.testclient import TestClient

from app import services
from app.main import app

USERS = "http://users:8000/api/v1"
CHANNELS = "http://channels:8000/api/v1"
MESSAGES = "http://messages:8000/api/v1"
OZY = "http://ozy:8000/api/v1"
SEARCH = "http://search:8000/api/v1"
SUMMARIES = "http://summaries:8000/api/v1"


@pytest.fixture
def mock():
    services.display_names.clear()
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(mock):
    return TestClient(app)


@pytest.fixture
def gql(client):
    """Ejecuta una operación GraphQL y devuelve el cuerpo de la respuesta."""
    def run(query: str, **variables):
        response = client.post("/graphql", json={"query": query, "variables": variables})
        assert response.status_code == 200
        return response.json()
    return run
