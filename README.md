# mini_pacs_edge

Edge DICOM Gateway for hospital edge without Kubernetes. Simulates C-STORE reception, a persistent local queue, typical edge failures, and worker routing for SRE diagnosis.

```
ORTHANC/PACS -> [C-STORE] -> edge (receiver/queue/forwarder) -> workers -> edge -> ORTHANC/PACS
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
3) Edge envia C-STORE a un worker (round-robin).
4) Worker devuelve un DICOM de resultado al edge (C-STORE).
5) Edge detecta resultado (`SeriesDescription=AI_RESULT`) y reenvia a Orthanc/PACS.

### Ports

- edge (DICOM): 11112
- orthanc (DICOM): 4242, HTTP: 8042
- ohif (HTTP): 3000

### Config

Archivo: `config.yaml`

- `edge.ae_title`, `edge.port`, rutas de data/logs.
- `forwarder.mode: gateway` para ruteo automatico.
- `forwarder.workers`: lista de workers con `host`, `port`, `ae_title`.
- `forwarder.orthanc`: destino PACS/Orthanc (host/port/AET).

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
python sender_simulator.py ./path/to/dicom
```

Burst send:

```sh
python sender_simulator.py ./dicoms --burst 5 --delay-ms 50
```

### Ver estudios en OHIF

- Abrir `http://localhost:3000` en el navegador.

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
- El edge envia C-STORE a un worker (round-robin).
- El worker devuelve un objeto DICOM de resultado al edge (C-STORE).
- El edge reenvia el resultado a Orthanc/PACS.

Config en `config.yaml`:

- `forwarder.mode: gateway` para ruteo automatico.
- `forwarder.workers`: lista de workers con `host`, `port`, `ae_title`.

Los resultados de los workers se marcan con `SeriesDescription = AI_RESULT` y se reenvian a Orthanc/PACS.

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
