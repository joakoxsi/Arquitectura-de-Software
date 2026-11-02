# ADR-004: En el clúster, leer los mensajes por API y publicar en un broker propio

- **Estado:** aceptada
- **Fecha:** 2026-11-02
- **Reemplaza en parte a:** [ADR-003](ADR-003-despliegue-kubernetes-junto-al-core.md)
  (punto 2, que suponía un broker del curso)

## Contexto

Al revisar el clúster del curso, el chat base (`servicios-base`) **no tiene
broker**: el Deployment de `messages` solo recibe `MONGODB_URL`, `USERS_URL` y
`CHANNELS_URL`. Sin `RABBITMQ_URL`, su código guarda `chat.message.created` solo en
su lista en memoria (`GET /api/v1/events`), que el README de la base describe
como un recurso «solo para explorar el contrato localmente».

Ozy necesita enterarse de los mensajes para su read-model, y la regla es usar
exclusivamente los contratos publicados, sin modificar ni redesplegar el core.
Los contratos REST publicados sí permiten leer mensajes:
`GET /api/v1/channels` y `GET /api/v1/channels/{channel_id}/messages`.

Otros grupos del curso despliegan su propio RabbitMQ en su namespace.

## Decisión

1. **Entrada por API (*polling consumer*).** En el clúster, Ozy lee los mensajes
   con un sincronizador (`app/synchronizer.py`) que cada 5 s recorre canales y
   mensajes por la API pública y copia los nuevos a `messages_read_model` pasando
   por la misma capa anticorrupción que el consumidor de eventos.
   - Corre dentro de las réplicas de la API, pero **solo una sincroniza a la vez**
     gracias a un *lease* en la MongoDB de Ozy: escalar con el HPA no multiplica la
     carga sobre el chat base, que es compartido por todos los grupos.
   - `POST …/translation?channel_id=` sincroniza ese canal al momento, para que un
     mensaje recién creado se pueda traducir sin esperar el ciclo.
2. **Salida por un broker propio.** Ozy publica sus eventos
   (`chat.translation.created`, `chat.glossary.*`) en el exchange `chat` de un
   RabbitMQ en su namespace (`ozy-rabbitmq`). Las credenciales salen de un secret
   de GitHub y nunca quedan en el repo.
3. **La fuente se elige por configuración**, sin ramas de código por entorno:
   `CONSUME_MESSAGE_EVENTS=true` (compose, valor por defecto) consume
   `chat.message.created` del broker donde publica `messages`; `false` (clúster)
   usa el sincronizador y deja el broker solo para publicar.
4. Los eventos que Ozy emite también se guardan en su MongoDB
   (`published_events`), así que `GET /api/v1/events` responde lo mismo desde
   cualquier réplica.

## Consecuencias

- **Latencia:** un mensaje aparece en Ozy hasta ~5 s después de crearse (o al
  instante con `channel_id`). Para traducir bajo demanda es aceptable.
- **Costo sobre el core:** un ciclo hace 1 + N peticiones (N = canales). Con un solo
  sincronizador y 5 s de intervalo es bajo; si el número de canales creciera mucho,
  habría que subir el intervalo o pedir al curso un contrato incremental
  (por ejemplo, mensajes desde una fecha).
- **Cuota:** el broker usa un pod más; el HPA queda en 2–4 réplicas para que todo
  quepa con la carga de prueba corriendo. RabbitMQ va sin volumen porque la cuota
  permite un solo PVC (usado por MongoDB).
- **Reversible:** si el curso agrega un broker a `servicios-base`, basta con
  apuntar `RABBITMQ_URL` a él y poner `CONSUME_MESSAGE_EVENTS=true`; Ozy vuelve a
  consumir eventos sin cambios de código.
