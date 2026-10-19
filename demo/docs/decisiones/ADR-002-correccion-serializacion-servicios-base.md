# ADR-002: Corregir la serialización al crear recursos en los servicios base

- **Estado:** aceptada
- **Fecha:** 2026-10-18
- **Contexto de origen:** prueba de punta a punta de Ozy

## Contexto

Al preparar la prueba de punta a punta de Ozy se detectó que los servicios base
`users`, `channels` y `messages` responden `500 Internal Server Error` cada vez
que crean un recurso, aunque el recurso sí queda guardado.

La causa está en pymongo (versión 4.12.1, la fijada en los `requirements.txt`):
`insert_one(doc)` **agrega el campo `_id` (un `ObjectId`) al mismo diccionario
que recibe**. Los tres servicios devuelven ese diccionario como respuesta, y
FastAPI no sabe convertir un `ObjectId` a JSON.

En `messages` el efecto es mayor. Después de insertar, el mismo diccionario se
usa para armar el evento `chat.message.created`, y `json.dumps` falla antes de
publicarlo. El error no es `AMQPError`, así que no lo captura el `try` existente:
**el evento nunca llega a RabbitMQ** y ningún consumidor (como Ozy) puede
recibir mensajes.

## Decisión

Insertar una copia del diccionario en los tres servicios:

```python
users.insert_one({**user})        # users/app/main.py
channels.insert_one({**channel})  # channels/app/main.py
messages.insert_one({**message})  # messages/app/main.py
```

pymongo agrega `_id` a la copia, y la respuesta y el evento usan el diccionario
original, que solo tiene tipos serializables.

## Cómo afecta al sistema

- **`users`, `channels` y `messages`:** `POST` responde `201` con el recurso
  creado, como describe su contrato. El documento guardado en MongoDB es idéntico
  al de antes (sigue teniendo su `_id` interno, que las lecturas ya excluían con
  la proyección `{"_id": 0}`).
- **`messages` → RabbitMQ:** `chat.message.created` ahora sí se publica. Sin esta
  corrección, el flujo asíncrono de Ozy no funciona.
- **`GET /api/v1/events` de los servicios base:** antes también fallaba, porque
  la lista en memoria guardaba el diccionario con `ObjectId`. Ahora responde bien.
- **Contratos:** no cambian. Ni la forma de las respuestas ni la de los eventos.
- **Alcance:** es la única modificación al código de los servicios base. Es una
  línea por servicio y no cambia su lógica.

## Alternativas descartadas

- **Excluir `_id` en la respuesta** (`user.pop("_id")` o un `response_model`):
  corrige la respuesta, pero en `messages` el evento se arma con el mismo
  diccionario, así que habría que corregir dos lugares en vez de uno.
- **Dejar los servicios base sin cambios y documentar el error:** Ozy no podría
  recibir mensajes y el sistema no funcionaría de punta a punta con
  `docker compose up`.
