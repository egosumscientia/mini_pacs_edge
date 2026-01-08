import os
from typing import Any

import pydicom
from pynetdicom import evt

from fault_injector.faults import FaultError, apply_faults, simulate_disk_full
from queue_store.queue_manager import enqueue
from receiver.config import get_config, log_event


def handle_store(event: evt.Event) -> int:
    config = get_config()
    ds = event.dataset
    ds.file_meta = event.file_meta

    study_uid = getattr(ds, "StudyInstanceUID", "unknown")
    sop_uid = getattr(ds, "SOPInstanceUID", "unknown")
    ae_title_raw = event.assoc.acceptor.ae_title
    if isinstance(ae_title_raw, bytes):
        ae_title = ae_title_raw.decode(errors="ignore")
    else:
        ae_title = str(ae_title_raw)
    remote_ip = event.assoc.requestor.address

    try:
        apply_faults("receive")
        data_root = config["edge"]["data_root"]
        dest_dir = os.path.join(data_root, "incoming", study_uid)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{sop_uid}.dcm")
        simulate_disk_full(dest_path)
        pydicom.filewriter.dcmwrite(dest_path, ds, write_like_original=False)

        enqueue(study_uid, sop_uid, dest_path)

        log_event(
            "info",
            "store",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=ae_title,
            remote_ip=remote_ip,
            outcome="stored",
            error=None,
        )
        log_event(
            "info",
            "queue",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=ae_title,
            remote_ip=remote_ip,
            outcome="queued",
            error=None,
        )
        return 0x0000
    except FaultError as exc:
        log_event(
            "error",
            "receive",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=ae_title,
            remote_ip=remote_ip,
            outcome="rejected",
            error=str(exc),
        )
        return 0xA700
    except Exception as exc:  # noqa: BLE001
        log_event(
            "error",
            "store",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=ae_title,
            remote_ip=remote_ip,
            outcome="failed",
            error=str(exc),
        )
        return 0xA700


def handle_echo(event: evt.Event) -> int:
    _ = event
    return 0x0000
