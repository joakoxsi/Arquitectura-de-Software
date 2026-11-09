# Búsqueda de mensajes con Elasticsearch, desplegada en Kubernetes

Capacidad vertical **«Motor de búsqueda avanzada»** sobre el chat base del curso
(`users`, `channels`, `messages` en el namespace `servicios-base`). Inspirada en
*How Discord Indexes Billions of Messages*.

**Video de demostración:** https://youtu.be/u_zxx0Ojhoc

## Arquitectura desplegada

```
 core del curso (servicios-base)            namespace grupo-busqueda-avanzada
 ┌────────────────────────┐   polling   ┌────────────────┐  _bulk  ┌───────────────┐
 │ channels  GET /channels│◄────────────│ search-indexer │────────►│ Elasticsearch │
 │ messages  GET /channels│  (5 s)      └────────────────┘         │ alias messages│
 │           /{id}/messages│                                       └───────▲───────┘
 └────────────────────────┘             cliente ─► Ingress ─► search (API) ─┘
                                                       (HPA 1–3 réplicas)
```

* **Sin tocar el core.** El enunciado prohíbe modificarlo y el cluster no tiene
  broker, así que `search-indexer` consulta cada `POLL_SECONDS` sus APIs públicas
  (`GET /api/v1/channels` y `GET /api/v1/channels/{id}/messages`). No lee sus bases.
* **Idempotente.** Cada documento usa el id del mensaje con `op_type=create`; un 409
  significa «ya indexado». Reiniciar el indexador reenvía todo una vez sin duplicar.
* **Consistencia eventual.** Un mensaje nuevo aparece tras el siguiente poll (5 s) más
  el `refresh` de Elasticsearch (1 s).
* **`search` no tiene estado**, por eso es lo único que escala con el HPA. El indexador
  tiene 1 réplica (no comparte cursor).
* Índice físico `messages-v1` detrás del alias `messages`; `routing = channel_id`.

## API

`GET /api/v1/search/messages` (todos los canales) y
`GET /api/v1/channels/{channel_id}/messages/search` (un canal).

| Parámetro | Descripción |
| --- | --- |
| `content` | Texto (todas las palabras; sin distinguir mayúsculas ni tildes) |
| `author_id` | Uno o más autores |
| `channel_id` | Uno o más canales (solo búsqueda global) |
| `mentions` | Usuarios mencionados con `<@id>` |
| `has` | `link`, `mention` |
| `min_date`, `max_date` | Rango de `created_at` (ISO 8601) |
| `sort_by`, `sort_order` | `timestamp` (defecto) o `relevance`; `desc` (defecto) o `asc` |
| `limit`, `offset` | 1–25 y 0–9975 |

Salud: `GET /health` (liveness, sin dependencias) y `GET /health/ready` (readiness,
503 si Elasticsearch no responde).

## Despliegue en Kubernetes

Manifiestos en [`k8s/`](k8s/), dentro de la cuota del namespace (1 Gi de memoria en
requests, 1 PVC de 1 Gi, 10 pods):

| Archivo | Contenido |
| --- | --- |
| `elasticsearch.yaml` | StatefulSet de 1 nodo (heap 256 MB) + Service + PVC 1 Gi |
| `search.yaml` | API: Deployment, Service, ConfigMap y **HPA** (1–3 réplicas, CPU 50 %) con readiness y liveness |
| `indexer.yaml` | Indexador (1 réplica); liveness por *heartbeat* (`/tmp/heartbeat`) |
| `ingress.yaml` | Ingress Traefik hacia `search` |

Todos los pods cumplen PodSecurity `restricted` (no root, sin escalada, seccomp).

**CI** ([`.github/workflows/deploy-busqueda.yaml`](../.github/workflows/deploy-busqueda.yaml)):
en cada push a `main` que toque esta carpeta construye la imagen y la sube a GHCR
(`ghcr.io/mochytk/busqueda-search`, paquete público), reemplaza `:latest` por el SHA del
commit y ejecuta `kubectl apply -f k8s/` y `rollout status`. Requiere el secret de
GitHub `KUBE_CONFIG` (kubeconfig en base64); nunca va en el repo.

Despliegue manual:

```bash
kubectl -n grupo-busqueda-avanzada apply -f k8s/
kubectl -n grupo-busqueda-avanzada get pods,hpa,ingress
```

## Evidencia ([`evidencia/`](evidencia/))

* `flujo-integrado.yaml` / `.log`: crea usuario, canal y mensaje en el core desplegado y
  lo encuentra en `search` (0 resultados al instante, 1 a los 12 s).
* `carga.yaml` / `escalamiento-hpa.txt`: bajo carga el HPA pasa de 1 a 3 réplicas
  (pico 160 % de CPU) y vuelve a 1 al terminar.

## Correr en local (docker compose)

```bash
docker compose up -d --build   # users, channels, messages, search, indexer, Elasticsearch, web
python3 seed.py                # datos de ejemplo
```

Interfaz y gateway nginx en http://localhost:8080. El `messages` local es una versión
modificada (outbox, PATCH/DELETE) usada solo en desarrollo; el indexador la consulta por
polling igual que al core del cluster.

## Limitaciones conocidas

* Solo se indexan mensajes creados (el core base no edita ni borra) y cada ciclo lista
  todos los canales: con mucho volumen habría que paginar o usar un cursor persistido.
* `GET /api/v1/search/status` consulta la API de gestión de RabbitMQ, que no existe en el
  cluster: allí devuelve `null` en `pending_events` y `dead_letter_events`.
* Elasticsearch corre con 256 MB de heap por la cuota; puede ser inestable con mucha carga.
* El host del Ingress es provisional (`busqueda.example.com`), sin TLS.
* No hay *stemming*: buscar «reunión» no encuentra «reuniones».

Propuesta original de la capacidad: [presentación](./Presentacion_capacidad_vertical.pdf)
(describe la variante local con RabbitMQ/outbox).

## Declaración de uso de IA

Se usó Claude Code (Claude Sonnet 5.5, de Anthropic) como asistente: ayudó a escribir el
servicio de búsqueda y su indexador, los manifiestos, el CI, la prueba de carga y este
README, y a diagnosticar errores de despliegue. El grupo definió los requisitos, revisó y
ejecutó el código, lo desplegó en el cluster, verificó el funcionamiento y grabó el video.
Los commits hechos con la herramienta llevan `Co-Authored-By`.
