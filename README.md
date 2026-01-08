# mini_pacs_edge

Edge DICOM Gateway for hospital edge without Kubernetes. Simulates C-STORE reception, a persistent local queue, typical edge failures, and worker routing for SRE diagnosis.

```
ORTHANC/PACS -> [C-STORE] -> edge (receiver/queue)
                                | \
                                |  +-> workers (async) -> edge -> ORTHANC/PACS
                                +-> ORTHANC/PACS (original, immediate)
                                |
                                +-> PostgreSQL (queue/state)
```

## Architecture

### Components

- edge: Gateway DICOM SCP + queue + forwarder (Python).
- workers (app01..app05): DICOM SCP simulando IA. Reciben C-STORE del edge y devuelven un resultado DICOM al edge.
- orthanc: PACS/archivo DICOM (hospital/clinica).
- ohif: Visor web conectado directo a Orthanc (no pasa por edge).
- postgres: Persistencia de la cola/estado.

### Data flow (DICOM TCP)

1) Orthanc/PACS envia C-STORE al edge.
2) Edge guarda en `data/incoming`, encola en PostgreSQL.
3) Edge envia INMEDIATAMENTE el DICOM original a Orthanc/PACS (C-STORE).
4) En paralelo, edge envia el mismo DICOM a un worker (round-robin, async).
5) El worker devuelve un DICOM de resultado al edge (C-STORE).
6) Edge detecta resultado (`SeriesDescription=AI_RESULT`), correlaciona y reenvia a Orthanc/PACS.

### Ports

- edge (DICOM): 11112
- orthanc (DICOM): 4242 (solo red interna), HTTP: 8042 (publicado)
- ohif (HTTP): 3000

### Config

Archivo: `config.yaml`

- `edge.ae_title`, `edge.port`, rutas de data/logs.
- `edge.allowed_calling_aets`: allowlist de Calling AE Titles (incluye Orthanc y workers).
- `forwarder.mode: parallel` para envio inmediato a PACS + worker async.
- `forwarder.workers`: lista de workers con `host`, `port`, `ae_title`.
- `forwarder.orthanc`: destino PACS/Orthanc (host/port/AET).
- `forwarder.worker_timeout_seconds`: timeout simple por worker.

Nota: si usas `sender_simulator.py` desde el host, usa `--calling-aet ORTHANC` o agrega ese AET a `edge.allowed_calling_aets`.

## Run (lab)

### Requisitos

- Docker Desktop o Docker Engine con Docker Compose.
- Python 3.11+ si quieres usar `sender_simulator.py` desde host.

### Levantar servicios

```sh
docker compose up --build
```

### Enviar un estudio desde el host

```sh
python sender_simulator.py ./path/to/dicom --calling-aet ORTHANC
```

Burst send:

```sh
python sender_simulator.py ./dicoms --burst 5 --delay-ms 50 --calling-aet ORTHANC
```

Generar estudios dinamicos (sin archivos previos):

```sh
python sender_simulator.py --generate 3 --out-dir ./tmp_dicoms --calling-aet ORTHANC
```

Reescribir UIDs en cada envio (evita duplicados de Study/SOP):

```sh
python sender_simulator.py ./path/to/dicom --rewrite-uids --calling-aet ORTHANC
```

Reescribir UIDs manualmente:

```sh
python sender_simulator.py ./path/to/dicom --rewrite-uids --study-uid 1.2.3 --series-uid 1.2.3.4 --sop-uid 1.2.3.4.5 --calling-aet ORTHANC
```

Consecutivo de estudios (PostgreSQL):

```sh
docker exec -it mini_pacs_edge python /app/sender_simulator.py --generate 3 --seq-from-db --patient-id EDGE --patient-name TEST^EDGE --series-description SYNTHETIC --calling-aet ORTHANC
```

Resetear cola y consecutivo:

```sh
docker exec -it mini_pacs_edge python /app/cli.py reset-db
```

### Ver estudios en OHIF

- Abrir `http://localhost:3000` en el navegador.

### Limpiar Orthanc (base vacia)

```sh
docker compose down
rm -rf ./data/orthanc
docker compose up -d --build
```

### Logs utiles

```sh
docker compose logs -f edge
docker compose logs -f app01
docker compose logs -f orthanc
```

### Detener todo

```sh
docker compose down
```

## Workers (apps IA)

Los workers son DICOM SCP. El Gateway (edge) actua como DICOM SCU hacia los workers y hacia Orthanc/PACS.

- El edge recibe C-STORE desde Orthanc/PACS.
- El edge reenvia INMEDIATAMENTE el original a Orthanc/PACS.
- En paralelo, envia C-STORE a un worker (round-robin) sin bloquear al PACS.
- El worker devuelve un objeto DICOM de resultado al edge (C-STORE).
- El edge reenvia el resultado a Orthanc/PACS.

Config en `config.yaml`:

- `forwarder.mode: parallel` para flujo asincrono.
- `forwarder.workers`: lista de workers con `host`, `port`, `ae_title`.
- `forwarder.worker_timeout_seconds`: timeout simple por worker.

Los resultados de los workers se marcan con `SeriesDescription = AI_RESULT` y se reenvian a Orthanc/PACS.

Para pruebas de latencia, puedes usar `WORKER_DELAY_SECONDS` en el servicio del worker.

## Network isolation (Docker)

- `pacs_net`: edge + orthanc + ohif (+ postgres).
- `workers_net`: edge + workers.
- orthanc no esta en `workers_net`.
- workers no estan en `pacs_net`.

Esto bloquea acceso directo de workers a Orthanc.

## Faults (inside container)

```sh
docker exec -it mini_pacs_edge python /app/cli.py inject-fault reject_all
docker exec -it mini_pacs_edge python /app/cli.py inject-fault disk_full
docker exec -it mini_pacs_edge python /app/cli.py inject-fault io_delay_ms
docker exec -it mini_pacs_edge python /app/cli.py inject-fault random_fail_rate

docker exec -it mini_pacs_edge python /app/cli.py clear-faults
```

## SRE checklist (edge)

- Verify ports and AE Titles (`config.yaml`).
- Confirm volume writes in `data/` and `logs/`.
- Review `logs/edge.log` for JSON events per stage.
- Validate PostgreSQL in `data/postgres`.
- Review `data/queued`, `data/sent`, `data/failed`.
- Simulate faults and observe recovery/retries.

## Verify PostgreSQL

- Check service logs: `docker compose logs postgres`.
- Check table: `docker exec -it mini_pacs_edge-postgres-1 psql -U mini_pacs -d mini_pacs -c "\\dt"`.

## If PostgreSQL does not start

- Wait for edge retries (log `stage=db`).
- Check permissions on `data/postgres`.
- Remove the volume and recreate if corrupted.

## Ops notes

- Receiver accepts CT, MR, and Secondary Capture.
- Files are stored in `data/incoming/<StudyUID>/<SOPUID>.dcm`.
- Queue and states persist across restarts (PostgreSQL).

## Validation (lab)

### Checklist rapido (Nivel 2)

1) AE permitido entra y se procesa (debe llegar a worker y volver a Orthanc)

```sh
docker exec -it mini_pacs_edge python /app/sender_simulator.py /tmp/test.dcm --host edge --port 11112 --calling-aet ORTHANC --called-aet MINI_EDGE
docker compose logs edge | Select-String -Pattern "forward_pacs|forward_worker|ai_result"
```

2) AE no permitido es rechazado

```sh
docker exec -it mini_pacs_edge python /app/sender_simulator.py /tmp/test.dcm --host edge --port 11112 --calling-aet NOPE_AET --called-aet MINI_EDGE
docker compose logs edge | Select-String -Pattern "NOPE_AET|calling_aet_not_allowed"
```

3) Workers no alcanzan Orthanc por red

```sh
docker exec -it mini_pacs_edge-app01-1 python - <<'PY'
import socket
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect(("orthanc", 4242))
    print("UNEXPECTED: connected")
except Exception as exc:
    print("expected failure:", exc)
finally:
    sock.close()
PY
```

4) Worker apagado -> PACS sigue recibiendo original

```sh
docker compose stop app01
python sender_simulator.py ./path/to/dicom --calling-aet ORTHANC
docker compose logs edge | Select-String -Pattern "forward_pacs|forward_worker"
```

5) Worker lento -> PACS ya tenia el estudio, resultado llega despues

Configura un delay en un worker (ejemplo app01) y reinicia:

```sh
# en docker-compose.yml agrega en app01:
#   WORKER_DELAY_SECONDS: "12"
docker compose up -d --build app01
python sender_simulator.py ./path/to/dicom --calling-aet ORTHANC
docker compose logs edge | Select-String -Pattern "forward_pacs|ai_result"
```

### Enviar un estudio

```sh
python sender_simulator.py ./path/to/dicom --calling-aet ORTHANC
```

### Verificar aislamiento (workers -> orthanc debe fallar)

```sh
docker exec -it mini_pacs_edge-app01-1 python - <<'PY'
import socket
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect(("orthanc", 4242))
    print("UNEXPECTED: connected")
except Exception as exc:
    print("expected failure:", exc)
finally:
    sock.close()
PY
```

### Verificar allowlist de AE Titles (debe ser rechazado)

```sh
python sender_simulator.py ./path/to/dicom --calling-aet BAD_AET
```

Revisar logs:

```sh
docker compose logs -f edge
```

### Verificar trazabilidad en PostgreSQL

```sh
docker exec -it mini_pacs_edge python /app/cli.py status --study <StudyInstanceUID>
```

Y en logs (correlacion):

```sh
docker compose logs -f edge
```
