# ADR-001: Agregar RabbitMQ al docker-compose y conectarlo a `messages`

- **Estado:** aceptada
- **Fecha:** 2026-09-29
- **Contexto de origen:** implementación del microservicio Ozy (:8004)

## Contexto

Ozy necesita consumir el evento `chat.message.created` para mantener su propio
read-model de mensajes. El servicio `messages` ya tiene el código para publicar
en RabbitMQ (`messages/app/main.py`, función `publish`), pero **solo lo hace si
recibe la variable `RABBITMQ_URL`**. En la base entregada:

- no existía un contenedor de RabbitMQ en `docker-compose.yaml`;
- `messages` no recibía `RABBITMQ_URL`, así que cada evento quedaba únicamente
  en su lista en memoria (`GET /api/v1/events`) y nunca llegaba al broker.

Por eso no había forma de que otro servicio consumiera los eventos del chat.

## Decisión

1. Agregar al compose un servicio `rabbitmq` (imagen `rabbitmq:3-management`)
   en la red `microsvcs`, con el usuario `chat`/`chat` y los puertos 5672 (AMQP)
   y 15672 (consola web de administración).
2. Pasar `RABBITMQ_URL: amqp://chat:chat@rabbitmq:5672/` a `messages` y a `ozy`.

**No se modificó el código de `messages`**: solo su configuración en el compose.
Se activó una capacidad que ya estaba implementada.

¿Por qué un usuario propio y no `guest`? RabbitMQ solo acepta a `guest` desde
localhost. Un usuario explícito evita depender de cómo esté configurada la
imagen.

## Cómo afecta al sistema

### `messages`
- Ahora cada `POST /api/v1/channels/{id}/messages` abre una conexión AMQP y
  publica el evento en el exchange `chat` (tipo `topic`, routing key = tipo de
  evento). El sobre es `{type, subject_id, occurred_at, data}`.
- Esa conexión síncrona es nueva y está dentro de la petición HTTP, así que
  cada creación de mensaje tarda un poco más.
- Si el broker está caído, `messages` captura `AMQPError`, guarda el evento en
  su lista local y responde 201 igual. **La creación de mensajes no depende de
  RabbitMQ**, pero ese evento se pierde para los consumidores (no hay outbox ni
  reintentos, como ya advierte el comentario del código).

### `ozy`
- Consume desde una cola propia y durable, `ozy.chat.message.created`, enlazada
  al exchange `chat` con la routing key `chat.message.created`.
- Declara el exchange `chat` **con los mismos parámetros que `messages`**
  (`topic`, no durable). Si los declarara distintos, RabbitMQ rechazaría la
  declaración (`PRECONDITION_FAILED`).
- Si el broker no está disponible al arrancar, Ozy reintenta la conexión con
  backoff. El resto de la API (glosario, traducciones de mensajes ya recibidos)
  sigue funcionando mientras tanto.
- Publica sus propios eventos (`chat.translation.created` y `chat.glossary.*`) en
  el mismo exchange; el contrato completo está en el [README de Ozy](../../ozy/README.md#eventos).

### Acoplamiento y límites
- `messages` y `ozy` no se conocen: solo comparten el nombre del exchange y del
  tipo de evento (el contrato). Ozy no lee la base de datos de `messages`.
- Aparece una dependencia de infraestructura compartida: el broker.

### Riesgos conocidos
- **Mensajes publicados antes de que exista la cola de Ozy se pierden.** Un
  exchange `topic` descarta los mensajes que no tienen cola enlazada. Pasa, por
  ejemplo, si se crean mensajes antes del primer arranque de Ozy. Después, la
  cola durable los retiene aunque Ozy esté detenido.
- El exchange no es durable (así lo declara `messages`): si se reinicia el
  contenedor `rabbitmq`, el exchange y sus enlaces se recrean cuando los
  servicios lo vuelvan a declarar.
- Las credenciales `chat`/`chat` y la consola en el 15672 son adecuadas solo
  para el entorno local de desarrollo.

## Alternativas descartadas

- **Leer `GET messages:8003/api/v1/events` por polling:** la base aclara que ese
  endpoint es solo para explorar el contrato localmente. Además es memoria
  volátil y acoplaría Ozy a la disponibilidad de `messages`.
- **Leer la base `messages-mongodb` directamente:** viola la regla de la base
  de que ningún servicio accede a los datos internos de otro.
