import os
import threading
from typing import Any, Optional

import pydicom
from pynetdicom import evt

from fault_injector.faults import FaultError, apply_faults, simulate_disk_full
from forwarder.forwarder import ForwardError, Forwarder
from queue_store.models import AI_STATUS_FAILED, AI_STATUS_TIMEOUT, STATE_FAILED, STATE_SENT
from queue_store.queue_manager import (
    enqueue,
    mark_ai_status,
    mark_pacs_sent,
    mark_result_received,
    update_state,
)
from receiver.config import get_config, log_event


_FORWARDER: Optional[Forwarder] = None


def set_forwarder(forwarder: Forwarder) -> None:
    global _FORWARDER
    _FORWARDER = forwarder


def _get_forwarder() -> Forwarder:
    global _FORWARDER
    if _FORWARDER is None:
        _FORWARDER = Forwarder()
    return _FORWARDER


def _log_receive(study_uid: str, sop_uid: str, called_aet: str, calling_aet: str, remote_ip: str | None) -> None:
    log_event(
        "info",
        "receive",
        study_uid=study_uid,
        sop_uid=sop_uid,
        ae_title=called_aet,
        calling_aet=calling_aet,
        remote_ip=remote_ip,
        outcome="accepted",
        error=None,
    )


def _send_worker_async(
    item_id: int,
    source_path: str,
    study_uid: str,
    sop_uid: str,
    called_aet: str,
    calling_aet: str,
    remote_ip: str | None,
) -> None:
    forwarder = _get_forwarder()
    try:
        worker = forwarder.send_to_worker(source_path, item_id)
        log_event(
            "info",
            "forward_worker",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=called_aet,
            calling_aet=calling_aet,
            worker=worker,
            remote_ip=remote_ip,
            outcome="sent",
            error=None,
        )
    except ForwardError as exc:
        message = str(exc)
        status = AI_STATUS_TIMEOUT if "timeout" in message else AI_STATUS_FAILED
        mark_ai_status(item_id, status, message)
        log_event(
            "error",
            "forward_worker",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=called_aet,
            calling_aet=calling_aet,
            remote_ip=remote_ip,
            outcome=status,
            error=message,
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        mark_ai_status(item_id, AI_STATUS_FAILED, message)
        log_event(
            "error",
            "forward_worker",
            study_uid=study_uid,
            sop_uid=sop_uid,
            ae_title=called_aet,
            calling_aet=calling_aet,
            remote_ip=remote_ip,
            outcome="failed",
            error=message,
        )


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

        forwarder_mode = str(config.get("forwarder", {}).get("mode", "dummy")).lower()
        is_ai_result = str(getattr(ds, "SeriesDescription", "")).strip() == "AI_RESULT"

        _log_receive(study_uid, sop_uid, called_aet, calling_aet, remote_ip)
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

        if forwarder_mode == "parallel" and is_ai_result:
            correlation = mark_result_received(study_uid, sop_uid)
            worker_info = None
            duration_ms = None
            if correlation:
                worker_info = correlation["worker"]
                duration_ms = correlation["duration_ms"]
            forwarder = _get_forwarder()
            try:
                forwarder.send_to_orthanc(dest_path)
                log_event(
                    "info",
                    "ai_result",
                    study_uid=study_uid,
                    original_sop_uid=correlation["original_sop_uid"] if correlation else None,
                    result_sop_uid=sop_uid,
                    worker=worker_info,
                    duration_ms=duration_ms,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="forwarded",
                    error=None,
                )
            except ForwardError as exc:
                log_event(
                    "error",
                    "ai_result",
                    study_uid=study_uid,
                    original_sop_uid=correlation["original_sop_uid"] if correlation else None,
                    result_sop_uid=sop_uid,
                    worker=worker_info,
                    duration_ms=duration_ms,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="forward_failed",
                    error=str(exc),
                )
            if not correlation:
                log_event(
                    "warning",
                    "ai_result",
                    study_uid=study_uid,
                    result_sop_uid=sop_uid,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="unmatched",
                    error="no_original_found",
                )
            return 0x0000

        item_id = enqueue(study_uid, sop_uid, dest_path)
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

        if forwarder_mode == "parallel" and not is_ai_result:
            forwarder = _get_forwarder()
            try:
                forwarder.send_to_orthanc(dest_path)
                mark_pacs_sent(item_id)
                update_state(item_id, STATE_SENT)
                log_event(
                    "info",
                    "forward_pacs",
                    study_uid=study_uid,
                    sop_uid=sop_uid,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="sent",
                    error=None,
                )
            except ForwardError as exc:
                update_state(item_id, STATE_FAILED, last_error=str(exc))
                log_event(
                    "error",
                    "forward_pacs",
                    study_uid=study_uid,
                    sop_uid=sop_uid,
                    ae_title=called_aet,
                    calling_aet=calling_aet,
                    remote_ip=remote_ip,
                    outcome="failed",
                    error=str(exc),
                )

            worker_thread = threading.Thread(
                target=_send_worker_async,
                args=(item_id, dest_path, study_uid, sop_uid, called_aet, calling_aet, remote_ip),
                daemon=True,
            )
            worker_thread.start()
            return 0x0000

        if is_ai_result:
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
