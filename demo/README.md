# Base común: Chat en microservicios

Esta es la base funcional entregada al inicio de la Unidad 3. Los equipos la
levantan con `docker compose up --build`. Está formada por tres microservicios
independientes, cada uno dueño de sus datos:

| Servicio | Puerto | Responsabilidad |
| --- | --- | --- |
| `users` | 8001 | Crear y consultar usuarios |
| `channels` | 8002 | Crear y consultar canales |
| `messages` | 8003 | Crear y listar mensajes |
| `ozy` | 8004 | Traducir jerga técnica a lenguaje simple (ver [ozy/README.md](ozy/README.md)) |
| `gateway` | 8080 | API Gateway **GraphQL** (`/graphql`, con GraphiQL): único punto de entrada de la interfaz (ver [gateway/README.md](gateway/README.md)) |
| `frontend` | 3000 | Interfaz web (React) servida por nginx; `/graphql` va al gateway |
| `search` / `search-indexer` | 8005 | Búsqueda con Elasticsearch (capacidad de otro grupo, imagen `ghcr.io/mochytk/busqueda-search`) |
| `summaries` | 8006 | Resúmenes de canales con LLM (capacidad de otro grupo, imagen `ghcr.io/marcel-silva27/summaries-service`) |
| `rabbitmq` | 5672 / 15672 | Broker de eventos (exchange `chat`) |

La documentación OpenAPI de cada servicio está disponible en
`http://localhost:{8001,8002,8003,8004}/docs`. El servicio `messages` consulta las
APIs de `users` y `channels` para validar las referencias antes de crear un
mensaje. Ningún servicio accede a los datos internos de otro.

Cada servicio usa su propia instancia MongoDB y volumen Docker: `users-data`,
`channels-data` y `messages-data`.

## Cómo extenderla

Cada grupo crea un servicio propio y lo agrega al `docker-compose.yaml` con la
red `microsvcs`. La capacidad puede publicar rutas propias y consumir los
eventos de los servicios base; no debe leer ni escribir el estado de `users`,
`channels` o `messages`.

Cada servicio expone `GET /api/v1/events` solo para explorar su contrato
localmente. En las unidades de implementación se sustituye por un consumidor de
broker.

## Búsqueda de mensajes (Elasticsearch)

La búsqueda es la capacidad «Motor de búsqueda avanzada» de otro grupo
([repo](https://github.com/Mochytk/INF326-Arquitectura-de-Software_Tareas/tree/main/Tarea_Unidad_5_Despliegue)).
No se copia su código: en local se usa su imagen pública, y su indexador lee
nuestro core por polling de las APIs públicas (igual que en el clúster).

La interfaz solo habla con el gateway (query GraphQL `searchMessages`), que reenvía a
`search` y agrega el nombre del autor y del canal a cada resultado. Equivalencia con la
API REST de compatibilidad:

| Gateway | Servicio `search` |
| --- | --- |
| `GET /api/search/messages` | `GET /api/v1/search/messages` |
| `GET /api/channels/{id}/messages/search` | `GET /api/v1/channels/{id}/messages/search` |

Filtros: `content`, `channel_id`, `author_id`, `has` (`link`, `mention`),
`min_date`/`max_date`, `sort_by` (`timestamp`, `relevance`), `sort_order`, `limit`, `offset`.

**En el clúster del curso** su `search` vive en `grupo-busqueda-avanzada` y el
gateway lo llama **directo a su Service**: `http://search.grupo-busqueda-avanzada:8000`.
La NetworkPolicy `conexiones-del-grupo` permite el tráfico entre namespaces de
estudiantes. No se usa su Ingress: desde un pod, Traefik y la IP pública expiran.
Configuración y verificación en
[ozy/k8s/README.md](ozy/k8s/README.md#conexión-con-los-servicios-de-otros-grupos).

## Resúmenes de canales (LLM)

Capacidad de otro grupo ([repo](https://github.com/marcel-silva27/summaries-service)),
usada con su imagen pública. Lee el core solo por sus APIs y trae su propia MongoDB y
RabbitMQ (`summaries-mongodb`, `summaries-rabbitmq`). Es asíncrono: se pide el
resumen (202 + `summary_id`) y la interfaz consulta hasta `completada` o `fallida`.

| Gateway | Servicio `summaries` |
| --- | --- |
| `POST /api/channels/{id}/summaries` | `POST /api/v1/channels/{id}/summaries` (cuerpo opcional `{user_id, timeInterval: {start, end}}`) |
| `GET /api/channels/{id}/summaries` | `GET /api/v1/channels/{id}/summaries` |
| `GET /api/channels/{id}/summaries/latest` | `GET /api/v1/channels/{id}/summaries/latest` |
| `GET /api/summaries/{id}` | `GET /api/v1/summaries/{id}` |

En la interfaz: botón **✦ Resumir** en cada canal → «Lo nuevo» (mensajes aún no
resumidos) o «Por fechas», con el historial de resúmenes del canal.

**En el clúster del curso** su `summaries` vive en `grupo-resumenes` y el gateway lo
llama directo a su Service, que expone el **puerto 80**: `http://summaries.grupo-resumenes`.
Allí usa Gemini con la key de ese grupo; si su cuota se agota, el resumen termina
`fallida` con el motivo en `error`.

En local, por defecto corre con el proveedor `mock` (respuestas simuladas, sin API
key). Para usar Gemini, crear `demo/.env` (no se versiona) con:

```
SUMMARIES_LLM_PROVIDER=gemini
LLM_API_KEY=<tu key de Gemini>
```
