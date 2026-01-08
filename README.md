# mini_pacs_edge

Edge DICOM Receiver for hospital edge without Kubernetes. Simulates C-STORE reception, a persistent local queue, typical edge failures, and a dummy forwarder for SRE diagnosis.

```
SENDER -> [C-STORE] -> edge (receiver/queue/forwarder) -> PostgreSQL
```

## Start

```sh
docker compose up --build
```

## Send studies

```sh
python sender_simulator.py ./path/to/dicom
```

Burst send:

```sh
python sender_simulator.py ./dicoms --burst 5 --delay-ms 50
```

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

- Receiver accepts CT and MR Storage.
- Files are stored in `data/incoming/<StudyUID>/<SOPUID>.dcm`.
- Queue and states persist across restarts (PostgreSQL).
