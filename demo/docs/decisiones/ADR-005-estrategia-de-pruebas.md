# ADR-005: Pruebas de servicio, de contrato e integración para Ozy

- **Estado:** aceptada
- **Fecha:** 2026-11-16

## Contexto

Ozy tenía 74 tests con `mongomock`. Para reemplazar la base de datos, los tests
cambiaban con `monkeypatch` la variable global `main.repos`. Faltaban tres cosas
para la entrega:

- **Pruebas de servicio** por endpoint, con casos de error y una BD de pruebas
  aislada de forma explícita: override de dependencias de FastAPI o una fixture que
  cree y destruya la base.
- **Pruebas de contrato** con el chat base. Ozy depende de la forma de
  `chat.message.created` y de las respuestas de `users`, `channels` y `messages`,
  pero `test_acl.py` usaba un sobre escrito a mano. Si `messages` cambiaba su
  evento, nada fallaba hasta el despliegue. Los servicios base no declaran modelos
  de respuesta, así que su OpenAPI no sirve como contrato.
- **Una prueba de integración** en Docker Compose, reducida a `users`, `channels`
  y `messages`. `scripts/e2e.py` necesita el compose completo (Elasticsearch,
  resúmenes, gateway, interfaz) y no corre como test de pytest.

## Decisión

1. **Repositorios por inyección de dependencias.** Las rutas reciben
   `repos: Repositories = Depends(get_repos)`. La fixture `repos` crea en cada test
   una base `chat_ozy_test_<uuid>` y la registra con
   `app.dependency_overrides[get_repos]`. Al terminar hace `drop_database` y quita
   el override. El arranque (índices y seed) y el consumidor usan `active_repos()`,
   que respeta el override, así que todo el test usa la misma base. La base es
   `mongomock` por defecto. Con `OZY_TEST_MONGODB_URL` se usa una MongoDB real.
2. **Contratos dirigidos por el consumidor, en JSON Schema.** Están en
   `tests/contract/contracts/`, uno por cada evento o API que Ozy consume, más el
   evento propio `chat.translation.created`. Solo exigen los campos que Ozy usa y
   permiten campos extra (lector tolerante). Cada contrato se verifica por los dos
   lados:
   - **Consumidor:** el código de Ozy acepta el ejemplo del contrato.
   - **Proveedor:** el `app/main.py` real del servicio base se carga en el mismo
     proceso, con una MongoDB en memoria propia de la prueba, y lo que responde o
     publica debe cumplir el schema.

   No se accede a la base de otro servicio ni se levanta el sistema. Se eligió
   JSON Schema con `jsonschema` en vez de Pact porque no necesita un broker de
   contratos y los proveedores no son de este grupo.
3. **Compose propio para la integración.** Se usa `demo/docker-compose.test.yaml`
   con healthchecks, sin volúmenes, con su propia red y en otros puertos.
   `scripts/integracion.sh` lo levanta, corre `pytest -m integration` y lo destruye.
   En CI es el job `integration`, del que depende la publicación de imágenes.
4. **Organización.** Los tests están en `tests/unit`, `tests/service`,
   `tests/contract` y `tests/integration`, y cada carpeta define su marker. Con
   `pytest` a secas no corre la integración (`addopts = -m "not integration"`).

## Consecuencias

- Un cambio incompatible en el evento o en las APIs del chat base hace fallar las
  pruebas de proveedor en el PR, antes del despliegue. Para comprobarlo, se renombró
  `content` en el evento de `messages`: fallaron 4 pruebas de contrato.
- Las pruebas de proveedor dependen de que el código del chat base esté en el
  repositorio, en `demo/users`, `demo/channels` y `demo/messages`. Si no está, se
  omiten con un aviso. El workflow también corre cuando cambia ese código.
- El chat base desplegado en el clúster podría diferir del que está en el
  repositorio. Esa diferencia la sigue cubriendo la prueba integrada del clúster
  (Job `ozy-e2e`).
- La integración agrega cerca de un minuto al CI, más el build de las imágenes.
- `main.repos` sigue existiendo como valor por defecto de `get_repos`, así que el
  comportamiento en producción no cambia.
