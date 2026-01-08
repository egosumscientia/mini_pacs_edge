import os
import shutil
import time

import pydicom
from pynetdicom import AE
from pynetdicom.sop_class import CTImageStorage, MRImageStorage

from fault_injector.faults import FaultError, apply_faults, simulate_disk_full
from queue_store.models import STATE_FAILED, STATE_FORWARDING, STATE_QUEUED, STATE_SENT
from queue_store.queue_manager import get_next_queued, increment_retry, update_state
from receiver.config import get_config, log_event


class ForwardError(RuntimeError):
    pass


class Forwarder:
    def __init__(self) -> None:
        self.config = get_config()
        forwarder_config = self.config["forwarder"]
        self.mode = str(forwarder_config.get("mode", "dummy")).lower()
        if self.mode not in {"dummy", "orthanc"}:
            raise ValueError(f"Unsupported forwarder mode: {self.mode}")
        self.max_retries = int(forwarder_config["max_retries"])
        self.backoff_base = int(forwarder_config["backoff_base_seconds"])
        self.poll_interval = int(forwarder_config["poll_interval_seconds"])
        self.data_root = self.config["edge"]["data_root"]
        self.orthanc = forwarder_config.get("orthanc", {})

    def run(self) -> None:
        while True:
            item = get_next_queued()
            if item is None:
                time.sleep(self.poll_interval)
                continue

            try:
                queued_path = self._move_to_queued(item.file_path, item.study_uid, item.sop_uid)
                update_state(item.id, STATE_FORWARDING, file_path=queued_path)
                item.file_path = queued_path

                apply_faults("forward")
                time.sleep(0.2)

                if self.mode == "orthanc":
                    self._send_to_orthanc(queued_path)

                sent_path = self._move_to_sent(queued_path, item.study_uid, item.sop_uid)
                update_state(item.id, STATE_SENT, file_path=sent_path)
                self._log_forward(item.study_uid, item.sop_uid, result="sent", error=None)
            except (FaultError, OSError, ForwardError) as exc:
                self._handle_failure(item, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._handle_failure(item, str(exc))

    def _move_to_queued(self, source_path: str, study_uid: str, sop_uid: str) -> str:
        dest_dir = os.path.join(self.data_root, "queued", study_uid)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{sop_uid}.dcm")
        simulate_disk_full(dest_path)
        shutil.move(source_path, dest_path)
        return dest_path

    def _move_to_sent(self, source_path: str, study_uid: str, sop_uid: str) -> str:
        dest_dir = os.path.join(self.data_root, "sent", study_uid)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{sop_uid}.dcm")
        simulate_disk_full(dest_path)
        shutil.move(source_path, dest_path)
        return dest_path

    def _move_to_failed(self, source_path: str, study_uid: str, sop_uid: str) -> str:
        dest_dir = os.path.join(self.data_root, "failed", study_uid)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{sop_uid}.dcm")
        simulate_disk_full(dest_path)
        shutil.move(source_path, dest_path)
        return dest_path

    def _send_to_orthanc(self, source_path: str) -> None:
        host = str(self.orthanc.get("host", "orthanc"))
        port = int(self.orthanc.get("port", 4242))
        called_aet = str(self.orthanc.get("ae_title", "ORTHANC"))
        timeout_s = float(self.orthanc.get("timeout_s", 10))

        ae = AE(ae_title=self.config["edge"]["ae_title"])
        ae.add_requested_context(CTImageStorage)
        ae.add_requested_context(MRImageStorage)
        ae.acse_timeout = timeout_s
        ae.dimse_timeout = timeout_s
        ae.network_timeout = timeout_s

        try:
            assoc = ae.associate(host, port, ae_title=called_aet)
        except TimeoutError as exc:
            raise ForwardError("timeout") from exc
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "timed out" in message.lower():
                raise ForwardError("timeout") from exc
            raise ForwardError(f"association_error:{message}") from exc

        if not assoc.is_established:
            raise ForwardError("association_refused")

        try:
            ds = pydicom.dcmread(source_path)
            status = assoc.send_c_store(ds)
        except TimeoutError as exc:
            raise ForwardError("timeout") from exc
        except Exception as exc:  # noqa: BLE001
            raise ForwardError(f"c_store_error:{exc}") from exc
        finally:
            assoc.release()

        if status is None:
            raise ForwardError("c_store_no_status")
        status_code = getattr(status, "Status", None)
        if status_code != 0x0000:
            raise ForwardError(f"c_store_failure:{status_code}")

    def _handle_failure(self, item, error: str) -> None:
        self._log_forward(item.study_uid, item.sop_uid, result="failed", error=error)
        increment_retry(item.id, error)
        new_retries = item.retries + 1
        if new_retries >= self.max_retries:
            try:
                failed_path = self._move_to_failed(item.file_path, item.study_uid, item.sop_uid)
                update_state(item.id, STATE_FAILED, file_path=failed_path, last_error=error)
            except Exception as exc:  # noqa: BLE001
                update_state(item.id, STATE_FAILED, last_error=f"{error};move_failed:{exc}")
            return

        update_state(item.id, STATE_QUEUED, last_error=error)
        backoff = self.backoff_base * (2 ** (new_retries - 1))
        log_event(
            "warning",
            "forward",
            study_uid=item.study_uid,
            sop_uid=item.sop_uid,
            ae_title=self.config["edge"]["ae_title"],
            remote_ip=None,
            outcome="retry",
            error=error,
        )
        time.sleep(backoff)

    def _log_forward(self, study_uid: str, sop_uid: str, result: str, error: str | None) -> None:
        level = "info" if result == "sent" else "error"
        log_event(
            level,
            "forward",
            study_uid=study_uid,
            sop_uid=sop_uid,
            study_instance_uid=study_uid,
            sop_instance_uid=sop_uid,
            destination=self.mode,
            result=result,
            error=error,
        )
