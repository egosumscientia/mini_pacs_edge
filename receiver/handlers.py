import os
from typing import Any

import pydicom
from pynetdicom import evt

from fault_injector.faults import FaultError, apply_faults, simulate_disk_full
from queue_store.queue_manager import enqueue, mark_result_received
from receiver.config import get_config, log_event


def handle_store(event: evt.Event) -> int:
    config = get_config()
    ds = event.dataset
    ds.file_meta = event.file_meta

    study_uid = getattr(ds, "StudyInstanceUID", "unknown")
    sop_uid = getattr(ds, "SOPInstanceUID", "unknown")
    calling_raw = event.assoc.requestor.ae_title
    if isinstance(calling_raw, bytes):
        calling_aet = calling_raw.decode(errors="ignore")
    else:
        calling_aet = str(calling_raw)
    called_raw = event.assoc.acceptor.ae_title
    if isinstance(called_raw, bytes):
        called_aet = called_raw.decode(errors="ignore")
    else:
        called_aet = str(called_raw)
    remote_ip = event.assoc.requestor.address

    try:
        allowed = config["edge"].get("allowed_calling_aets", [])
        if allowed and calling_aet not in allowed:
            log_event(
                "error",
                "receive",
                study_uid=study_uid,
                sop_uid=sop_uid,
                ae_title=called_aet,
                calling_aet=calling_aet,
                remote_ip=remote_ip,
                outcome="rejected",
                error="calling_aet_not_allowed",
            )
            return 0xA700

        apply_faults("receive")
        data_root = config["edge"]["data_root"]
        dest_dir = os.path.join(data_root, "incoming", study_uid)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{sop_uid}.dcm")
        simulate_disk_full(dest_path)
        pydicom.filewriter.dcmwrite(dest_path, ds, write_like_original=False)

        enqueue(study_uid, sop_uid, dest_path)
        if getattr(ds, "SeriesDescription", "") == "AI_RESULT":
            correlation = mark_result_received(study_uid, sop_uid)
            if correlation:
                log_event(
                    "info",
                    "result",
                    study_uid=study_uid,
                    original_sop_uid=correlation["original_sop_uid"],
                    result_sop_uid=sop_uid,
                    worker=correlation["worker"],
                    duration_ms=correlation["duration_ms"],
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="correlated",
                    error=None,
                )
            else:
                log_event(
                    "warning",
                    "result",
                    study_uid=study_uid,
                    result_sop_uid=sop_uid,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="unmatched",
                    error="no_original_found",
                )

        log_event(
            "info",
            "store",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=called_aet,
            calling_aet=calling_aet,
            remote_ip=remote_ip,
            outcome="stored",
            error=None,
        )
        log_event(
            "info",
            "queue",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=called_aet,
            calling_aet=calling_aet,
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
            ae_title=called_aet,
            calling_aet=calling_aet,
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
            ae_title=called_aet,
            calling_aet=calling_aet,
            remote_ip=remote_ip,
            outcome="failed",
            error=str(exc),
        )
        return 0xA700


def handle_echo(event: evt.Event) -> int:
    _ = event
    return 0x0000
