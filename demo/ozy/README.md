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
10. [Despliegue en Kubernetes](#despliegue-en-kubernetes)
11. [Decisiones y limitaciones](#decisiones-y-limitaciones)
12. [Uso de IA](#uso-de-ia)

---

## Cómo levantarlo

Requisito: Docker Desktop (o Docker Engine + Compose v2).

[Configura la contraseña local de RabbitMQ](../README.md#ejecución-local) y
ejecuta desde `demo/`.

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
| Consola de RabbitMQ | <http://localhost:15672> (usuario `chat`, contraseña de `RABBITMQ_PASSWORD`) |

### Variables de entorno

| Variable | Obligatoria | Valor en compose | Uso |
|---|---|---|---|
| `MONGODB_URL` | sí | `mongodb://ozy-mongodb:27017` | Base propia `chat_ozy` |
| `RABBITMQ_URL` | no | `amqp://chat:${RABBITMQ_PASSWORD}@rabbitmq:5672/` | Sin ella Ozy no consume ni publica al broker |
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
│   ├── synchronizer.py   # sin broker: lee mensajes por la API del chat base
│   ├── publisher.py      # publicación de eventos
│   ├── detector.py       # detección de términos y candidatos
│   ├── translator.py     # motor de traducción (glosario + plantillas)
│   ├── users_client.py   # consulta opcional a users
│   └── seed.py           # glosario inicial
├── scripts/e2e.py        # prueba de punta a punta (compose o Job en Kubernetes)
├── scripts/integracion.sh # prueba de integración en Docker Compose
├── scripts/carga.py      # generador de carga para el HPA
├── k8s/                  # manifiestos, Jobs de prueba y scripts de evidencia
└── tests/                # pytest: unit/, service/, contract/, integration/
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
| `messages_read_model` | `message_id`, `channel_id`, `author_id`, `content`, `received_at` | `message_id` (+ índice no único `channel_id`, `message_id` para la sincronización por canal) |
| `glossary_entries` | `id`, `term`, `term_normalized`, `definition`, `ambito`, `estado`, `created_at`, `validated_by`, `validated_at` | `id` · (`term_normalized`, `ambito`) |
| `translations` | `translation_id`, `message_id`, `channel_id`, `audience_level`, `explanation`, `terms[]`, `created_at` | (`message_id`, `audience_level`) |
| `published_events` | `type`, `subject_id`, `occurred_at`, `data` | — (índice por `occurred_at`) |
| `leases` | `_id`, `owner`, `expires_at` | `_id` (una sola réplica sincroniza a la vez) |

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
| `GET` | `/health/live` | Liveness: proceso y consumidor de eventos vivos | 200 | 503 |
| `GET` | `/health/ready` | Readiness: su MongoDB responde | 200 | 503 |
| `POST` | `/api/v1/messages/{message_id}/translation` | Traduce un mensaje del read-model. `?channel_id=` opcional: sin broker, sincroniza ese canal en el momento | 201 | 404, 422 |
| `GET` | `/api/v1/messages/{message_id}/translation` | Traducción guardada (botón «Explícamelo en simple») | 200 | 404, 422 |
| `GET` | `/api/v1/glossary` | Lista el glosario. Filtros opcionales `?ambito=` y `?estado=` | 200 | 422 |
| `GET` | `/api/v1/glossary/{term}` | Todas las entradas de un término, por ámbito | 200 | 404 |
| `PATCH` | `/api/v1/glossary/{entry_id}/validation` | Valida o rechaza una definición | 200 | 404, 409, 422 |
| `GET` | `/api/v1/events` | Eventos publicados por Ozy (últimos 500, guardados en su base: iguales desde cualquier réplica) | 200 | — |

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

### Cómo recibe Ozy los mensajes

| Entorno | Fuente | Cómo |
|---|---|---|
| Local (compose) | Broker: `chat.message.created` | Consumidor RabbitMQ (`app/consumer.py`) |
| Clúster del curso | API pública del chat base | Sincronizador (`app/synchronizer.py`): cada 5 s lee `GET /api/v1/channels` y `GET /api/v1/channels/{id}/messages` |

El `messages` desplegado por el curso no tiene `RABBITMQ_URL`, así que no publica
eventos. Por eso, en el clúster Ozy arranca con `CONSUME_MESSAGE_EVENTS=false` (o
sin `RABBITMQ_URL`) y, si tiene `CHANNELS_URL` y `MESSAGES_URL`, usa el
sincronizador en vez del consumidor. Sus eventos propios los sigue publicando, en
su RabbitMQ propio ([ADR-004](../docs/decisiones/ADR-004-ingesta-por-api-y-broker-propio.md)). Ambos pasan por la
**misma capa anticorrupción** y escriben en el **mismo read-model**, así que el
resto de Ozy no cambia. Con varias réplicas, solo la que tiene el *lease* en
`leases` sincroniza, para no multiplicar la carga sobre el chat base compartido;
si esa réplica muere, otra toma el lease al vencer (30 s).

Un mensaje recién creado aparece en el read-model en el siguiente ciclo. Para
traducirlo al instante, el cliente puede pasar `?channel_id=` en el `POST`.

### Consumidos (con broker)

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

`GET /api/v1/events` devuelve los últimos 500 eventos emitidos por Ozy. Se guardan
en su base (`published_events`), así que la lista es la misma desde cualquier
réplica y sobrevive a reinicios.

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

Hay cuatro tipos de prueba, en carpetas distintas de `tests/`. Con `pytest` a secas
corren los tres primeros (110 tests, ~2 s, sin Docker). La integración se pide
aparte porque necesita Docker Compose.

| Tipo | Carpeta | Tests | Qué demuestra | Docker |
|---|---|---|---|---|
| Unitarias | `tests/unit/` | 48 | Lógica interna: detector, ACL, consumidor, sincronizador, publicador, arranque | No |
| De servicio | `tests/service/` | 39 | Cada endpoint de la API con TestClient y BD de pruebas aislada | No |
| De contrato | `tests/contract/` | 23 | Lo que Ozy consume del chat base (y lo que publica) cumple contratos versionados | No |
| De integración | `tests/integration/` | 7 | El flujo completo con `users`, `channels` y `messages` reales en Docker Compose | Sí |

```bash
cd ozy
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip install -r requirements-dev.txt     # Linux / macOS
.venv/Scripts/python -m pytest -v                   # unitarias + servicio + contrato
.venv/Scripts/python -m pytest -m service -v        # solo un tipo: unit, service o contract
```

### Base de datos de pruebas

Las pruebas nunca tocan la base de Ozy. Las rutas reciben los repositorios con
`Depends(get_repos)`, y la fixture `repos` de [`tests/conftest.py`](tests/conftest.py)
hace tres cosas en cada test:

1. crea una base nueva y vacía, `chat_ozy_test_<uuid>`;
2. la inyecta con `app.dependency_overrides[get_repos]`, y el arranque (índices y
   seed) también la usa;
3. al terminar, la destruye con `drop_database` y quita el override.

Por defecto la base es MongoDB en memoria (`mongomock`). Para correr la misma suite
contra una MongoDB real, se define `OZY_TEST_MONGODB_URL`:

```bash
docker run -d --rm --name ozy-test-mongo -p 27999:27017 mongo:7
OZY_TEST_MONGODB_URL=mongodb://localhost:27999 .venv/bin/python -m pytest
```

`TestAislamiento` comprueba que, después de una petición, la base de Ozy sigue vacía.

### Pruebas de servicio: dos o más por endpoint, con casos de error

[`tests/service/test_endpoints.py`](tests/service/test_endpoints.py) tiene una clase
por endpoint. Ozy no tiene autenticación, así que los casos de error son de entrada
inválida, recurso inexistente, conflicto o método no permitido.

| Endpoint | Tests | Casos de error |
|---|---|---|
| `GET /health` | 3 | 405 método no permitido |
| `GET /health/live` | 3 | 503 hilo consumidor muerto |
| `GET /health/ready` | 2 | 503 MongoDB caída |
| `POST /api/v1/messages/{id}/translation` | 7 | 404 mensaje inexistente (sin eventos) · 422 nivel inválido · 422 cuerpo que no es objeto |
| `GET /api/v1/messages/{id}/translation` | 5 | 404 nivel no generado · 404 mensaje inexistente · 422 nivel inválido |
| `GET /api/v1/glossary` | 4 | 422 ámbito inexistente · 422 estado inexistente |
| `GET /api/v1/glossary/{term}` | 3 | 404 término inexistente |
| `PATCH /api/v1/glossary/{id}/validation` | 7 | 404 entrada inexistente (sin eventos) · 422 candidato sin definición · 422 cuerpo inválido · 409 ámbito repetido |
| `GET /api/v1/events` | 3 | 405 método no permitido |

### Pruebas de contrato con el chat base

Los contratos son JSON Schema versionados en
[`tests/contract/contracts/`](tests/contract/contracts/). Cada uno indica quién lo
provee y quién lo consume (`x-provider`, `x-consumer`), y trae un ejemplo.

| Contrato | Proveedor → consumidor | Lo usa |
|---|---|---|
| `chat.message.created` (evento) | `messages` → Ozy | Consumidor RabbitMQ + capa anticorrupción |
| `GET /api/v1/users/{id}` | `users` → Ozy | `display_name` del autor |
| `GET /api/v1/channels` | `channels` → Ozy | Sincronizador (clúster sin broker) |
| `GET /api/v1/channels/{id}/messages` | `messages` → Ozy | Sincronizador (clúster sin broker) |
| `chat.translation.created` (evento) | Ozy → suscriptores | Evento propio de Ozy |

Cada contrato se verifica por los dos lados:

- **Consumidor:** Ozy acepta el ejemplo del contrato, tolera campos nuevos (lector
  tolerante) y rechaza lo mismo que el contrato rechaza.
- **Proveedor:** se carga el `app/main.py` real de `users`, `channels` y `messages`
  en el mismo proceso. Cada uno tiene su propia MongoDB en memoria, creada para la
  prueba, y funciona sin broker. Lo que responde o publica debe cumplir el schema.
  `messages` valida al autor y al canal contra `users` y `channels` reales, también
  en memoria. No se accede a la base de ningún otro servicio ni se levanta el sistema.

Si alguien cambia la forma del evento de `messages`, por ejemplo renombrando
`content`, las pruebas de proveedor fallan antes de llegar al clúster.

### Prueba de integración en Docker Compose

[`tests/integration/test_flujo_compose.py`](tests/integration/test_flujo_compose.py)
corre contra [`docker-compose.test.yaml`](../docker-compose.test.yaml). Ese compose
trae solo `users`, `channels`, `messages`, Ozy, RabbitMQ y una MongoDB por servicio.
No usa volúmenes, tiene su propia red y usa los puertos 18001–18004, 18672 y 18673,
así que no choca con el entorno de desarrollo. Desde `demo/`:

```bash
PYTHON=ozy/.venv/bin/python ozy/scripts/integracion.sh    # KEEP=1 deja el entorno arriba
```

El script levanta el entorno (`up --build --wait`), corre
`pytest -m integration tests/integration` y destruye el entorno (`down -v`), pase o
falle. Si algo falla, muestra los logs. La prueba recorre este flujo:

1. Ozy está listo y consume del broker (`ingestion: broker`).
2. Se crean un usuario en `users` y un canal en `channels`, y se publica un mensaje
   en `messages`.
3. `messages` emite `chat.message.created`, RabbitMQ lo entrega y Ozy lo guarda en su
   read-model y lo traduce.
4. La traducción trae el `display_name` real, leído desde `users`.
5. Ozy publica `chat.translation.created` y `chat.glossary.candidate.registered`. La
   prueba los escucha en el exchange `chat`.
6. Se valida el candidato, se emite `chat.glossary.entry.validated` y la siguiente
   traducción ya conoce el término.
7. Errores entre servicios: `messages` rechaza un autor o un canal inexistentes, y
   Ozy responde 404 a un mensaje que nunca se publicó.

En CI corre como el job `integration` del workflow `ozy-k8s`.

### Prueba de punta a punta

Con el sistema levantado (`docker compose up --build`), desde `demo/`:

```bash
python ozy/scripts/e2e.py
```

Recorre el flujo completo con los servicios reales (usuario → canal → mensaje →
evento → traducción → validación → eventos publicados → errores) y verifica cada
paso. Se diferencia de la prueba de integración en que corre contra el sistema
completo, sea el compose de desarrollo o el clúster (Job `ozy-e2e`). La
[guía de ejecución y pruebas](../docs/guia-ejecucion-y-pruebas.md) explica todos los
niveles de prueba y cómo resolver los problemas más comunes.

---

## Despliegue en Kubernetes

Ozy se despliega en el clúster común del curso, en el namespace del grupo y con
su propia MongoDB, **sin redesplegar ni modificar el chat base**: como ahí
`messages` no publica eventos, Ozy lee los mensajes por la API pública de
`channels` y `messages`, consulta `users` para el nombre del autor y publica sus
eventos en un RabbitMQ propio. Incluye startup/liveness/readiness probes, HPA
(2–4 réplicas por CPU, dentro de la cuota del grupo), PDB y un pipeline de GitHub Actions que
prueba, publica la imagen, despliega y corre una prueba integrada dentro del
clúster. Toda la guía, y los scripts que generan la evidencia del flujo
integrado y del escalamiento, están en [k8s/README.md](k8s/README.md). La
decisión está en
[ADR-003](../docs/decisiones/ADR-003-despliegue-kubernetes-junto-al-core.md) y
[ADR-004](../docs/decisiones/ADR-004-ingesta-por-api-y-broker-propio.md).

Cada respuesta HTTP incluye la cabecera `X-Ozy-Instance` con el pod que respondió.

---

## Decisiones y limitaciones

**Decisiones**

- [ADR-001](../docs/decisiones/ADR-001-broker-rabbitmq-en-compose.md): se agregó
  RabbitMQ al compose y se conectó `messages` (solo configuración, sin tocar su
  código).
- [ADR-002](../docs/decisiones/ADR-002-correccion-serializacion-servicios-base.md):
  se corrigió en los servicios base un error de serialización que impedía a
  `messages` publicar `chat.message.created` (una línea por servicio).
- [ADR-005](../docs/decisiones/ADR-005-estrategia-de-pruebas.md): pruebas de
  servicio con BD aislada por `dependency_overrides`, contratos con el chat base
  en JSON Schema verificados en ambos lados, e integración en un compose propio.
- Motor determinista (glosario + plantillas) en vez de un LLM: resultados
  reproducibles, sin costo ni dependencia externa, y fáciles de testear.
- Un candidato se completa con el mismo `PATCH` de validación (definición +
  ámbito), para que un término detectado pueda llegar a ser útil.

**Limitaciones conocidas**

- No detecta plurales ni flexiones: «los PRs» o «los deploys» no se reconocen.
- Una palabra corta escrita en mayúsculas (por ejemplo «HOY») puede registrarse
  como candidato.
- No hay *outbox* completo: si RabbitMQ está caído al publicar, el evento queda
  registrado en `published_events` pero no se reintenta su envío al broker.
- En el clúster del curso, un mensaje nuevo tarda hasta un ciclo (5 s) en
  llegar al read-model, salvo que se pida con `?channel_id=`. El sincronizador
  relee todos los canales en cada ciclo porque la API de `messages` no permite
  pedir solo los mensajes nuevos.
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
- **Despliegue en Kubernetes:** manifiestos, probes, HPA, pipeline de GitHub
  Actions, scripts de evidencia y la ADR-003, a partir del enunciado de la
  entrega. Se ensayaron en un clúster k3s local con un chat base simulado antes
  de usarlos en el clúster del curso.

### Revisión

El grupo revisó el código, los tests y la documentación generados, y aprobó cada
fase antes de continuar. El grupo es responsable del resultado final.

