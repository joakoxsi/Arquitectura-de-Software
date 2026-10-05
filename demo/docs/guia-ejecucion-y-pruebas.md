# Guía de ejecución y pruebas

Guía práctica para levantar el sistema, probar Ozy y diagnosticar problemas.
Para la referencia de la API y los eventos, ver [ozy/README.md](../ozy/README.md).

Hay tres niveles de prueba, de más rápido a más completo:

| Nivel | Qué prueba | Necesita Docker | Tiempo |
|---|---|---|---|
| [1. Tests unitarios](#1-tests-unitarios-pytest) | Lógica de Ozy aislada (54 tests) | No | ~2 s |
| [2. Prueba de punta a punta](#2-prueba-de-punta-a-punta-script) | Flujo completo con todos los servicios reales | Sí | ~1 min |
| [3. Prueba manual](#3-prueba-manual-swagger) | Explorar la API desde el navegador | Sí | libre |

## Requisitos

- **Docker Desktop** abierto y corriendo (o Docker Engine + Compose v2).
- **Python 3.12** solo para los tests unitarios y el script de punta a punta.
- Puertos libres: 8001–8004, 5672 y 15672.

---

## 1. Tests unitarios (pytest)

No necesitan Docker: usan MongoDB en memoria (`mongomock`) y simulan RabbitMQ y
el servicio `users`.

La primera vez, desde `demo/ozy/`:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
```

En Linux o macOS la ruta es `.venv/bin/` en vez de `.venv/Scripts/`.

Cada vez que quieras correrlos:

```bash
.venv/Scripts/python -m pytest -v
```

Variantes útiles:

```bash
.venv/Scripts/python -m pytest tests/test_api.py -v      # un archivo
.venv/Scripts/python -m pytest -k ambiguous -v           # por nombre
.venv/Scripts/python -m pytest -x                        # parar en el primer fallo
```

Resultado esperado: `54 passed`.

---

## 2. Prueba de punta a punta (script)

[`ozy/scripts/e2e.py`](../ozy/scripts/e2e.py) recorre el flujo completo contra
los servicios reales y verifica cada paso. Solo usa la biblioteca estándar de
Python.

**Paso 1.** Levanta el sistema desde `demo/`:

```bash
docker compose up --build
```

**Paso 2.** En otra terminal, también desde `demo/`:

```bash
python ozy/scripts/e2e.py
```

El script espera a que los servicios y la cola de Ozy estén listos, y luego:

1. crea un usuario, un canal y un mensaje con jerga (`PR`, `pipeline`, `KPI` y una
   sigla al azar);
2. espera a que Ozy reciba el evento `chat.message.created` y pide la traducción;
3. verifica que PR sea ambiguo (3 ámbitos) y que la sigla nueva quede como candidato;
4. consulta la traducción y verifica que traiga el nombre del autor desde `users`;
5. valida el candidato y comprueba que la siguiente traducción ya lo explica;
6. verifica los eventos publicados por Ozy;
7. comprueba los errores 404 y 422.

Resultado esperado: termina con `Todo el flujo funciona de punta a punta.` y
código de salida 0. Si algo falla, muestra el paso, la última respuesta HTTP y una
pista. Se puede ejecutar varias veces: cada corrida usa una sigla distinta.

---

## 3. Prueba manual (Swagger)

Con el sistema levantado, abre la documentación interactiva de cada servicio:

| Servicio | URL |
|---|---|
| users | <http://localhost:8001/docs> |
| channels | <http://localhost:8002/docs> |
| messages | <http://localhost:8003/docs> |
| **Ozy** | <http://localhost:8004/docs> |
| Consola de RabbitMQ | <http://localhost:15672> (usuario `chat`, clave `chat`) |

Orden sugerido:

1. users → `POST /api/v1/users` con `{"display_name": "Ana"}`. Copia el `id`.
2. channels → `POST /api/v1/channels` con `{"name": "general"}`. Copia el `id`.
3. messages → `POST /api/v1/channels/{channel_id}/messages` con
   `{"author_id": "<id>", "content": "Hice el PR pero el pipeline falló"}`. Copia el `id`.
4. Ozy → `POST /api/v1/messages/{message_id}/translation`.
5. Ozy → `GET /api/v1/messages/{message_id}/translation`, `GET /api/v1/glossary/PR`,
   `GET /api/v1/events`.

El mismo flujo con curl está en el [README de Ozy](../ozy/README.md#flujo-completo-con-curl).

---

## Comandos útiles

```bash
docker compose ps                    # estado de los contenedores
docker compose logs -f ozy           # log de Ozy en vivo
docker compose logs messages         # log de messages
docker compose restart ozy           # reiniciar solo Ozy
docker compose down                  # detener todo (conserva los datos)
docker compose down -v               # detener y BORRAR los datos (volúmenes)
docker compose up --build ozy        # reconstruir solo Ozy
```

El código de `app/` está montado como volumen y uvicorn corre con `--reload`: los
cambios en el código se aplican sin reconstruir. Si cambias `requirements.txt`,
hay que reconstruir con `--build`.

---

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `error during connect ... dockerDesktopLinuxEngine` | Docker Desktop no está abierto | Abrir Docker Desktop y esperar a que diga *Running* |
| Ozy muestra `RabbitMQ unavailable ... retrying` | RabbitMQ todavía está arrancando | Esperar; Ozy reintenta solo hasta ver `Consuming chat.message.created` |
| `POST …/translation` responde `404 Message not found` | Ozy no recibió el evento del mensaje | Ver las tres filas siguientes |
| — el mensaje se creó antes de que Ozy arrancara | La cola de Ozy aún no existía y RabbitMQ descartó el evento | Crear un mensaje nuevo después de ver `Consuming…` en el log de Ozy |
| — `messages` no publica | Falta `RABBITMQ_URL` en `messages` | Revisar `docker-compose.yaml` |
| — `POST` en users, channels o messages responde `500` | Error conocido de los servicios base (ver abajo) | Ver la sección siguiente |
| `display_name` es `null` | `users` no respondió | La traducción se entrega igual; revisar `docker compose logs users` |
| Puerto ocupado al levantar | Otro programa usa 8001–8004, 5672 o 15672 | Cerrar ese programa o cambiar el puerto publicado en el compose |
| Los tests fallan con `ModuleNotFoundError` | Dependencias no instaladas o otra carpeta | Correr desde `demo/ozy/` con el `.venv` creado |

### Error conocido de los servicios base

Los servicios `users`, `channels` y `messages` (entregados como base) responden
`500 Internal Server Error` al crear un recurso, aunque el recurso sí se guarda.

**Causa:** pymongo agrega un campo `_id` (de tipo `ObjectId`) al mismo diccionario
que recibe `insert_one`. Los servicios devuelven ese diccionario y FastAPI no sabe
convertir un `ObjectId` a JSON. En `messages` el problema es mayor: el error ocurre
al serializar el evento, así que **`chat.message.created` nunca llega a RabbitMQ**
y Ozy no puede recibir mensajes.

**Corrección mínima:** insertar una copia del diccionario, por ejemplo
`users.insert_one({**user})` en vez de `users.insert_one(user)`, y lo mismo en
`channels` y `messages`.
