# Ozy — traductor de jerga técnica

Microservicio del chat que detecta términos técnicos en los mensajes, mantiene un
**glosario con ámbito** y genera una **explicación en simple** de cada mensaje.

En equipos multidisciplinarios la misma sigla significa cosas distintas: «PR» es
*Pull Request* para Software, *Public Relations* para Marketing y *Purchase
Request* para Finanzas. Ozy hace visible esa ambigüedad en vez de esconderla.

| | |
|---|---|
| Puerto | `8004` |
| Stack | Python 3.12 · FastAPI · pymongo · pika (RabbitMQ) |
| Base de datos | MongoDB propia (`ozy-mongodb`, volumen `ozy-data`) |
| Versión de la API | `v1` (prefijo `/api/v1`, versión de la app `1.0.0`) |
| Documentación interactiva | <http://localhost:8004/docs> (Swagger) · <http://localhost:8004/redoc> |
| Esquema OpenAPI | <http://localhost:8004/openapi.json> |

## Contenido

1. [Cómo levantarlo](#cómo-levantarlo)
2. [Arquitectura](#arquitectura)
3. [Modelo de dominio](#modelo-de-dominio)
4. [API REST](#api-rest)
5. [Eventos](#eventos)
6. [Manejo de errores](#manejo-de-errores)
7. [Versionamiento](#versionamiento)
8. [Flujo completo con curl](#flujo-completo-con-curl)
9. [Tests](#tests)
10. [Decisiones y limitaciones](#decisiones-y-limitaciones)
11. [Uso de IA](#uso-de-ia)

---

## Cómo levantarlo

Requisito: Docker Desktop (o Docker Engine + Compose v2).

Desde la carpeta `demo/`:

```bash
docker compose up --build
```

Esto levanta los servicios base (`users`, `channels`, `messages`), **Ozy**, su
MongoDB y **RabbitMQ**. Cuando Ozy está listo para recibir eventos, su log muestra:

```
INFO:ozy.consumer:Consuming chat.message.created from queue ozy.chat.message.created
```

Antes de esa línea es normal ver `RabbitMQ unavailable ... retrying in Ns`: RabbitMQ
tarda unos segundos en arrancar y Ozy reintenta solo.

> **Importante:** crea mensajes *después* de ver esa línea la primera vez. Los
> mensajes publicados antes de que exista la cola de Ozy se pierden (ver
> [ADR-001](../docs/decisiones/ADR-001-broker-rabbitmq-en-compose.md)).

| Recurso | URL |
|---|---|
| Ozy (Swagger) | <http://localhost:8004/docs> |
| Consola de RabbitMQ | <http://localhost:15672> (usuario `chat`, clave `chat`) |

### Variables de entorno

| Variable | Obligatoria | Valor en compose | Uso |
|---|---|---|---|
| `MONGODB_URL` | sí | `mongodb://ozy-mongodb:27017` | Base propia `chat_ozy` |
| `RABBITMQ_URL` | no | `amqp://chat:chat@rabbitmq:5672/` | Sin ella Ozy no consume ni publica al broker |
| `USERS_URL` | no | `http://users:8000` | Para mostrar el `display_name` del autor |

---

## Arquitectura

```mermaid
flowchart LR
    UI["Cliente / UI"]
    M["messages :8003"]
    U["users :8001"]
    R[("RabbitMQ<br/>exchange chat")]
    subgraph Ozy["Ozy :8004"]
        C["Consumidor"] --> ACL["Capa anticorrupción"]
        ACL --> RM[("messages_read_model")]
        API["API REST"] --> T["Motor de traducción<br/>glosario + plantillas"]
        T --> G[("glossary_entries")]
        T --> TR[("translations")]
        API --> P["Publicador"]
    end
    M -->|"chat.message.created"| R
    R --> C
    UI -->|"HTTP"| API
    API -.->|"display_name opcional"| U
    P -->|"chat.translation.created<br/>chat.glossary.*"| R
```

Diagramas de secuencia (en la raíz del repositorio):
[1. Publicación de un mensaje técnico](<../../ozy-secuencias(1)-1. Publicación de un mensaje técnico.drawio.png>) ·
[2. Petición en simple](<../../ozy-secuencias(1)-2. Petición en simple (síncrono).drawio.png>) ·
[3. Traducción y evento propio](<../../ozy-secuencias(1)-3. Traducción y evento propio.drawio.png>)

### Principios

- **Dueño de sus datos.** Ozy solo lee y escribe en `ozy-mongodb`. Nunca accede a
  las bases de `users`, `channels` ni `messages`.
- **Referencias externas opacas.** Los ids de usuarios, canales y mensajes se
  guardan como strings; no se interpretan ni se validan contra otros servicios.
- **Capa anticorrupción** ([`app/acl.py`](app/acl.py)). Es el único módulo que
  conoce la forma de los eventos de `messages` y los traduce a `ReadMessage`.
  Si `messages` cambia su formato, solo cambia este archivo.
- **Read-model local.** Ozy guarda su propia copia de los mensajes al consumir
  `chat.message.created`, así que traducir no depende de que `messages` esté
  disponible.
- **Degradación elegante.** Si `users` falla, la traducción se entrega sin el
  nombre del autor; si RabbitMQ falla, la API sigue funcionando.

### Estructura

```
ozy/
├── app/
│   ├── main.py           # rutas FastAPI y arranque (índices, seed, consumidor)
│   ├── config.py         # variables de entorno
│   ├── domain.py         # modelo de dominio (lenguaje ubicuo)
│   ├── db.py             # conexión a MongoDB
│   ├── repositories.py   # acceso a las 3 colecciones
│   ├── acl.py            # capa anticorrupción
│   ├── consumer.py       # consumidor RabbitMQ con reconexión
│   ├── publisher.py      # publicación de eventos
│   ├── detector.py       # detección de términos y candidatos
│   ├── translator.py     # motor de traducción (glosario + plantillas)
│   ├── users_client.py   # consulta opcional a users
│   └── seed.py           # glosario inicial
├── scripts/e2e.py        # prueba de punta a punta contra el sistema levantado
└── tests/                # pytest (54 tests)
```

---

## Modelo de dominio

| Concepto | Significado |
|---|---|
| **Término** | Palabra, sigla o expresión con significado relevante para el equipo |
| **Definición** | Explicación asociada a un término |
| **Ámbito** | Contexto donde la definición es válida: `software`, `datos`, `producto`, `finanzas`, `marketing`, `operaciones`, `dominio` |
| **Estado** | `candidato` → `validado` o `rechazado` |
| **Validación** | Un integrante confirma (o rechaza) que una definición es correcta |
| **Entrada de glosario** | Un término + una definición en un ámbito. Es la entidad principal |
| **Nivel de audiencia** | `basico`, `intermedio` o `experto`: cambia la plantilla de la explicación |

Un mismo término puede tener **varias entradas con distinto ámbito**: así se
modela la ambigüedad. Un término es **ambiguo** cuando tiene definiciones no
rechazadas en dos o más ámbitos.

### Colecciones (MongoDB, base `chat_ozy`)

| Colección | Campos | Índice único |
|---|---|---|
| `messages_read_model` | `message_id`, `channel_id`, `author_id`, `content`, `received_at` | `message_id` |
| `glossary_entries` | `id`, `term`, `term_normalized`, `definition`, `ambito`, `estado`, `created_at`, `validated_by`, `validated_at` | `id` · (`term_normalized`, `ambito`) |
| `translations` | `translation_id`, `message_id`, `channel_id`, `audience_level`, `explanation`, `terms[]`, `created_at` | (`message_id`, `audience_level`) |

### Glosario inicial

Se carga al arrancar y no pisa cambios posteriores (si alguien rechaza una entrada
del seed, sigue rechazada después de reiniciar). Son 15 términos y 17 entradas,
todas `validado`:

| Ámbito | Términos |
|---|---|
| software | API, Deploy, Branch, **PR**, Pipeline |
| marketing | **PR**, CAC, Lead, Funnel |
| finanzas | **PR**, Devengado |
| datos | Modelo, KPI |
| producto | Backlog, Roadmap |
| operaciones | SLA, Incidencia |

### Motor de traducción

Determinista, sin LLM externo:

1. Busca cada término del glosario en el mensaje **sin distinguir mayúsculas y
   respetando límites de palabra** («APIs» no cuenta como «API»).
2. Las **siglas desconocidas** en mayúsculas (2–6 caracteres, como `ETL`) se
   registran como **candidatos** sin definición. Los términos rechazados no se
   vuelven a proponer.
3. Arma la explicación con la **plantilla del nivel de audiencia**:

| Nivel | Ejemplo para «Hice el PR pero el pipeline falló; revisen el KPI del ETL» |
|---|---|
| `basico` | «PR» significa cosas distintas según el área: en finanzas, Purchase Request…; en marketing, Public Relations…; en software, Pull Request… Confirma con quien escribió el mensaje a cuál se refiere. |
| `intermedio` | `- Pipeline (software): Cadena automática de pasos…` |
| `experto` | `Términos: PR [finanzas \| marketing \| software — ambiguo], Pipeline [software], KPI [datos], ETL [candidato].` |

---

## API REST

Todas las rutas de negocio están bajo `/api/v1`. Los cuerpos son JSON.

| Método | Ruta | Descripción | Éxito | Errores |
|---|---|---|---|---|
| `GET` | `/health` | Health-check | 200 | — |
| `POST` | `/api/v1/messages/{message_id}/translation` | Traduce un mensaje del read-model | 201 | 404, 422 |
| `GET` | `/api/v1/messages/{message_id}/translation` | Traducción guardada (botón «Explícamelo en simple») | 200 | 404, 422 |
| `GET` | `/api/v1/glossary` | Lista el glosario. Filtros opcionales `?ambito=` y `?estado=` | 200 | 422 |
| `GET` | `/api/v1/glossary/{term}` | Todas las entradas de un término, por ámbito | 200 | 404 |
| `PATCH` | `/api/v1/glossary/{entry_id}/validation` | Valida o rechaza una definición | 200 | 404, 409, 422 |
| `GET` | `/api/v1/events` | Eventos publicados por Ozy (lista en memoria, para explorar localmente) | 200 | — |

### `POST /api/v1/messages/{message_id}/translation`

Cuerpo opcional (sin cuerpo se usa `basico`):

```json
{ "audience_level": "basico" }
```

Respuesta `201` (recortada):

```json
{
  "translation_id": "a1c56447-8950-4541-8fb2-e63972e34a01",
  "message_id": "6f1c2a90-3b5e-4d7a-9c11-2e8f0a4b7d55",
  "channel_id": "b2d4e6f8-1a3c-4e5f-8a9b-0c1d2e3f4a5b",
  "audience_level": "basico",
  "explanation": "Este mensaje usa 4 términos técnicos. Explicado en simple:\n- «PR» significa cosas distintas según el área: ...",
  "terms": [
    {
      "term": "PR",
      "known": true,
      "ambiguous": true,
      "meanings": [
        { "entry_id": "277fe801-…", "ambito": "finanzas", "definition": "Purchase Request (solicitud de compra): …", "estado": "validado" },
        { "entry_id": "87d9eff7-…", "ambito": "marketing", "definition": "Public Relations (relaciones públicas): …", "estado": "validado" },
        { "entry_id": "f1e169d7-…", "ambito": "software", "definition": "Pull Request: …", "estado": "validado" }
      ]
    },
    { "term": "ETL", "known": false, "ambiguous": false, "meanings": [] }
  ],
  "created_at": "2026-10-05T02:46:52.400521+00:00"
}
```

Hay **una traducción por mensaje y nivel**: repetir el POST la regenera (con el
glosario actual) y reemplaza la anterior.

### `GET /api/v1/messages/{message_id}/translation?audience_level=basico`

Devuelve la misma estructura más el autor. `display_name` se pide a `users`; si
`users` no responde, es `null` y la respuesta sigue siendo `200`.

```json
{
  "translation_id": "a1c56447-8950-4541-8fb2-e63972e34a01",
  "audience_level": "basico",
  "…": "…",
  "author": { "id": "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a", "display_name": "Ana" }
}
```

### `GET /api/v1/glossary/{term}`

No distingue mayúsculas (`/glossary/pr` = `/glossary/PR`). Incluye las entradas
rechazadas para que se vea su estado, pero estas no cuentan para `ambiguous`.

```json
{
  "term": "PR",
  "ambiguous": true,
  "entries": [
    {
      "id": "277fe801-cbf1-4047-81b5-9b160b233675",
      "term": "PR",
      "definition": "Purchase Request (solicitud de compra): pedido interno formal para comprar un bien o servicio.",
      "ambito": "finanzas",
      "estado": "validado",
      "created_at": "2026-10-05T02:46:52.389026+00:00",
      "validated_by": null,
      "validated_at": null
    }
  ]
}
```

`GET /api/v1/glossary` devuelve una lista de entradas con esa misma forma.

### `PATCH /api/v1/glossary/{entry_id}/validation`

```json
{ "estado": "validado", "validated_by": "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a" }
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | `validado` \| `rechazado` | sí | `candidato` no se acepta |
| `validated_by` | string | sí | Id opaco de quien valida |
| `definition` | string | no | Para completar un candidato |
| `ambito` | enum de ámbitos | no | Para completar un candidato |

Un candidato (como `ETL`) se crea sin definición ni ámbito, así que para
validarlo hay que enviarlos:

```json
{
  "estado": "validado",
  "validated_by": "u1",
  "ambito": "datos",
  "definition": "Proceso que extrae, transforma y carga datos."
}
```

Responde la entrada actualizada, con `validated_by` y `validated_at`.

---

## Eventos

Ozy usa el exchange **`chat`** de RabbitMQ (tipo `topic`, no durable, igual que
`messages`). La routing key es el tipo de evento. Todos los eventos usan el mismo
sobre que los servicios base:

```json
{
  "type": "chat.translation.created",
  "subject_id": "<id de la entidad afectada>",
  "occurred_at": "2026-10-05T02:46:52.401550+00:00",
  "data": { "...": "..." }
}
```

### Consumidos

| Evento | Productor | Cola de Ozy | Efecto |
|---|---|---|---|
| `chat.message.created` | `messages` | `ozy.chat.message.created` (durable) | Upsert idempotente en `messages_read_model` |

Campos que Ozy toma de `data` (el resto se descarta en la capa anticorrupción):

| Campo | Tipo | Notas |
|---|---|---|
| `id` (o `message_id`) | string | Id opaco del mensaje |
| `channel_id` | string | Id opaco |
| `author_id` | string | Id opaco |
| `content` | string | Texto a traducir |

Ozy también acepta el payload plano `{message_id, channel_id, author_id, content}`.
Los eventos inválidos se descartan (sin reencolar) y se registran en el log.

### Publicados

Se emite **un evento por cada transacción que cambia el estado de Ozy**:

| Evento | Cuándo | `subject_id` |
|---|---|---|
| `chat.translation.created` | Cada `POST …/translation` exitoso | `translation_id` |
| `chat.glossary.candidate.registered` | Un `POST …/translation` encuentra una sigla nueva | `entry_id` |
| `chat.glossary.entry.validated` | `PATCH …/validation` con `validado` | `entry_id` |
| `chat.glossary.entry.rejected` | `PATCH …/validation` con `rechazado` | `entry_id` |

Las peticiones que fallan (404, 409, 422) no emiten eventos.

#### `chat.translation.created`

| Campo de `data` | Tipo | Descripción |
|---|---|---|
| `translation_id` | string (uuid) | Id de la traducción |
| `message_id` | string | Mensaje traducido |
| `channel_id` | string | Canal del mensaje |
| `audience_level` | `basico` \| `intermedio` \| `experto` | Nivel usado |
| `terms` | string[] | Términos detectados, en orden de aparición |

```json
{
  "type": "chat.translation.created",
  "subject_id": "a1c56447-8950-4541-8fb2-e63972e34a01",
  "occurred_at": "2026-10-05T02:46:52.401550+00:00",
  "data": {
    "translation_id": "a1c56447-8950-4541-8fb2-e63972e34a01",
    "message_id": "6f1c2a90-3b5e-4d7a-9c11-2e8f0a4b7d55",
    "channel_id": "b2d4e6f8-1a3c-4e5f-8a9b-0c1d2e3f4a5b",
    "audience_level": "basico",
    "terms": ["PR", "Pipeline", "KPI", "ETL"]
  }
}
```

#### `chat.glossary.candidate.registered`

| Campo de `data` | Tipo | Descripción |
|---|---|---|
| `entry_id` | string (uuid) | Entrada candidata creada |
| `term` | string | Sigla detectada |
| `message_id` | string | Mensaje donde apareció |
| `channel_id` | string | Canal del mensaje |

Se emite solo la primera vez que aparece el término; volver a traducir no lo repite.

#### `chat.glossary.entry.validated` / `chat.glossary.entry.rejected`

| Campo de `data` | Tipo | Descripción |
|---|---|---|
| `entry_id` | string (uuid) | Entrada modificada |
| `term` | string | Término |
| `ambito` | string \| null | Ámbito de la entrada |
| `estado` | `validado` \| `rechazado` | Nuevo estado |
| `validated_by` | string | Quién validó o rechazó |

`GET /api/v1/events` devuelve la lista de eventos publicados desde el último
arranque, igual que en los servicios base. Es solo para explorar localmente.

---

## Manejo de errores

Los errores de negocio responden con el formato estándar de FastAPI:

```json
{ "detail": "Message not found" }
```

| Código | `detail` | Cuándo |
|---|---|---|
| 404 | `Message not found` | POST de traducción de un mensaje que no está en el read-model |
| 404 | `Translation not found` | GET de una traducción que no se ha generado para ese nivel |
| 404 | `Term not found` | El término no existe en el glosario |
| 404 | `Glossary entry not found` | PATCH sobre un `entry_id` inexistente |
| 409 | `Term already has an entry for that ambito` | Se intenta asignar a un candidato un ámbito que el término ya tiene |
| 422 | `A validated entry needs a definition and an ambito` | Se valida un candidato sin enviar definición o ámbito |
| 422 | lista de errores de validación | Cuerpo o parámetros inválidos (nivel, ámbito o estado inexistente; falta `validated_by`) |

Ejemplo de `422` por validación de esquema:

```json
{
  "detail": [
    {
      "type": "enum",
      "loc": ["body", "audience_level"],
      "msg": "Input should be 'basico', 'intermedio' or 'experto'",
      "input": "x"
    }
  ]
}
```

### Fallas de dependencias

| Falla | Comportamiento |
|---|---|
| RabbitMQ caído al arrancar | El consumidor reintenta con backoff exponencial (1, 2, 4… hasta 30 s). La API responde normalmente |
| RabbitMQ caído al publicar | El evento queda en `GET /api/v1/events` y se registra un aviso; la petición responde con éxito |
| Evento con formato inválido | Se descarta sin reencolar (evita un bucle infinito) y se registra en el log |
| MongoDB falla al guardar un evento consumido | El mensaje vuelve a la cola para reintentarse |
| `users` caído o lento (timeout 2 s) | `display_name: null`; la traducción se entrega igual |

---

## Versionamiento

- **API:** la versión mayor va en la URL (`/api/v1`). Los cambios compatibles
  (campos nuevos, endpoints nuevos) se agregan a `v1`. Un cambio incompatible
  (renombrar o quitar campos, cambiar significados) se publicaría como `/api/v2`
  manteniendo `v1` mientras existan clientes.
- **Aplicación:** versión semántica en `FastAPI(version="1.0.0")`, visible en
  `/docs` y `/openapi.json`.
- **Eventos:** los consumidores deben ignorar campos desconocidos, así que agregar
  campos a `data` es compatible. Un cambio incompatible se publicaría con un tipo
  nuevo (por ejemplo `chat.translation.created.v2`) en paralelo al anterior.
- **Código:** historial en git; las decisiones de arquitectura se registran como
  ADR en [`docs/decisiones/`](../docs/decisiones/).

---

## Flujo completo con curl

Publicar un mensaje → Ozy lo consume → traducir → consultar. Los comandos son para
Git Bash o cualquier shell POSIX (en PowerShell usa `curl.exe` y cambia las
comillas, o usa Swagger en `/docs`). Requieren `python` para leer los ids.

```bash
# 1. Crear autor y canal (messages valida que existan)
USER_ID=$(curl -s -X POST localhost:8001/api/v1/users \
  -H "Content-Type: application/json" -d '{"display_name": "Ana"}' \
  | python -c "import sys, json; sys.stdout.write(json.load(sys.stdin)['id'])")

CHANNEL_ID=$(curl -s -X POST localhost:8002/api/v1/channels \
  -H "Content-Type: application/json" -d '{"name": "general"}' \
  | python -c "import sys, json; sys.stdout.write(json.load(sys.stdin)['id'])")

# 2. Publicar un mensaje técnico (messages emite chat.message.created)
MESSAGE_ID=$(curl -s -X POST localhost:8003/api/v1/channels/$CHANNEL_ID/messages \
  -H "Content-Type: application/json" \
  -d "{\"author_id\": \"$USER_ID\", \"content\": \"Hice el PR pero el pipeline falló; revisen el KPI del ETL\"}" \
  | python -c "import sys, json; sys.stdout.write(json.load(sys.stdin)['id'])")

# 3. Pedir la traducción a Ozy (usa su read-model)
curl -s -X POST localhost:8004/api/v1/messages/$MESSAGE_ID/translation \
  -H "Content-Type: application/json" -d '{"audience_level": "basico"}'

# 4. Consultarla (botón «Explícamelo en simple»); incluye el nombre del autor
curl -s localhost:8004/api/v1/messages/$MESSAGE_ID/translation

# 5. Explorar el glosario
curl -s localhost:8004/api/v1/glossary/PR
curl -s "localhost:8004/api/v1/glossary?estado=candidato"

# 6. Validar el candidato ETL
ENTRY_ID=$(curl -s localhost:8004/api/v1/glossary/ETL \
  | python -c "import sys, json; sys.stdout.write(json.load(sys.stdin)['entries'][0]['id'])")
curl -s -X PATCH localhost:8004/api/v1/glossary/$ENTRY_ID/validation \
  -H "Content-Type: application/json" \
  -d "{\"estado\": \"validado\", \"validated_by\": \"$USER_ID\", \"ambito\": \"datos\", \"definition\": \"Proceso que extrae, transforma y carga datos.\"}"

# 7. Ver los eventos que publicó Ozy
curl -s localhost:8004/api/v1/events
```

Si el paso 3 responde `404 Message not found`, Ozy no recibió el evento: revisa
`docker compose logs ozy` y que el mensaje se haya creado después de la línea
`Consuming…`.

---

## Tests

54 tests con pytest. No necesitan Docker: usan MongoDB en memoria (`mongomock`)
y simulan RabbitMQ y el servicio `users`.

```bash
cd ozy
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip install -r requirements-dev.txt     # Linux / macOS
.venv/Scripts/python -m pytest -v
```

| Archivo | Qué cubre |
|---|---|
| `test_acl.py` | Mapeo del sobre de `messages` y del payload plano, ids opacos, eventos inválidos |
| `test_detector.py` | Mayúsculas, límites de palabra, términos de varias palabras, candidatos, rechazados |
| `test_ambiguity.py` | PR con 3 ámbitos; efecto de rechazar definiciones; explicación de ambiguos |
| `test_consumer.py` | Idempotencia, ack/nack, reencolado, reconexión con backoff, declaración del exchange |
| `test_publisher_and_users.py` | Publicación al exchange, broker caído, `users` disponible y caído |
| `test_api.py` | Todos los endpoints, eventos emitidos por transacción y códigos de error |

### Prueba de punta a punta

Con el sistema levantado (`docker compose up --build`), desde `demo/`:

```bash
python ozy/scripts/e2e.py
```

Recorre el flujo completo con los servicios reales (usuario → canal → mensaje →
evento → traducción → validación → eventos publicados → errores) y verifica cada
paso. La [guía de ejecución y pruebas](../docs/guia-ejecucion-y-pruebas.md)
explica los tres niveles de prueba y cómo resolver los problemas más comunes.

---

## Decisiones y limitaciones

**Decisiones**

- [ADR-001](../docs/decisiones/ADR-001-broker-rabbitmq-en-compose.md): se agregó
  RabbitMQ al compose y se conectó `messages` (solo configuración, sin tocar su
  código).
- Motor determinista (glosario + plantillas) en vez de un LLM: resultados
  reproducibles, sin costo ni dependencia externa, y fáciles de testear.
- Un candidato se completa con el mismo `PATCH` de validación (definición +
  ámbito), para que un término detectado pueda llegar a ser útil.

**Limitaciones conocidas**

- No detecta plurales ni flexiones: «los PRs» o «los deploys» no se reconocen.
- Una palabra corta escrita en mayúsculas (por ejemplo «HOY») puede registrarse
  como candidato.
- No hay *outbox*: si RabbitMQ está caído al publicar, el evento solo queda en la
  lista local (mismo comportamiento que `messages`).
- Los mensajes publicados antes del primer arranque de Ozy no llegan a su cola.
- Para desambiguar, Ozy muestra todos los significados; no infiere el ámbito a
  partir del canal o del autor.

---

## Uso de IA

En este proyecto usamos inteligencia artificial y lo declaramos por honestidad
académica.

**Herramienta:** Claude Code (Anthropic), con el modelo Claude Opus 5.5.

### Qué hizo el grupo

El diseño del sistema es del grupo:

- La definición del problema: la ambigüedad de la jerga entre áreas de un equipo
  multidisciplinario.
- El modelo de dominio y su lenguaje ubicuo: término, definición, ámbito, estado,
  validación y entrada de glosario.
- La arquitectura de Ozy: microservicio dueño de sus datos, read-model propio,
  capa anticorrupción, comunicación por eventos con RabbitMQ, colecciones,
  endpoints, flujos y eventos.
- Los diagramas de arquitectura y de secuencia.
- Las decisiones de arquitectura, como agregar RabbitMQ al compose, el nombre de
  los contenedores, el formato de `/api/v1/events` y qué brechas cerrar frente a
  la pauta.
- La especificación que se entregó a la IA, dividida en fases, con revisión y
  aprobación al final de cada una.

### Qué hizo la IA

- **Generación de código:** el código de Ozy, los tests y el script de prueba de
  punta a punta, a partir de la especificación del grupo.
- **Borradores de documentación:** este README, la ADR-001 y la guía de
  ejecución, redactados sobre las decisiones del grupo.
- **Propuestas de detalles de implementación**, que el grupo aceptó o descartó.
  Por ejemplo: la política de reintentos del consumidor, los nombres de los
  niveles de audiencia, la heurística para detectar siglas y permitir completar
  un candidato desde la validación.
- **Revisión técnica**, como detectar que el evento real de `messages` no tenía
  la forma descrita en la especificación, o el error de serialización de los
  servicios base.

### Revisión

El grupo revisó el código, los tests y la documentación generados, y aprobó cada
fase antes de continuar. El grupo es responsable del resultado final.

