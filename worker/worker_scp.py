import datetime
import os
import time

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID, SecondaryCaptureImageStorage as SecondaryCaptureImageStorageUID, generate_uid
from pynetdicom import AE, evt
from pynetdicom.sop_class import CTImageStorage, MRImageStorage, SecondaryCaptureImageStorage


GATEWAY_HOST = os.getenv("GATEWAY_HOST", "edge")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "11112"))
GATEWAY_AE_TITLE = os.getenv("GATEWAY_AE_TITLE", "MINI_EDGE")
WORKER_AE_TITLE = os.getenv("WORKER_AE_TITLE", "WORKER")
WORKER_PORT = int(os.getenv("WORKER_PORT", "11112"))
WORKER_DELAY_SECONDS = float(os.getenv("WORKER_DELAY_SECONDS", "0"))


def _build_result(ds_in) -> FileDataset:
    now = datetime.datetime.utcnow()

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorageUID
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = getattr(ds_in, "StudyInstanceUID", generate_uid())
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = getattr(ds_in, "PatientName", "UNKNOWN")
    ds.PatientID = getattr(ds_in, "PatientID", "UNKNOWN")
    ds.Modality = "OT"
    ds.SeriesDescription = "AI_RESULT"
    ds.StudyDate = now.strftime("%Y%m%d")
    ds.StudyTime = now.strftime("%H%M%S")
    ds.Rows = 1
    ds.Columns = 1
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = b"\x00\x00"
    return ds


def _send_result(ds_result: FileDataset) -> None:
    ae = AE(ae_title=WORKER_AE_TITLE)
    ae.add_requested_context(SecondaryCaptureImageStorage)
    assoc = ae.associate(GATEWAY_HOST, GATEWAY_PORT, ae_title=GATEWAY_AE_TITLE)
    if not assoc.is_established:
        raise RuntimeError("gateway_association_refused")
    try:
        status = assoc.send_c_store(ds_result)
    finally:
        assoc.release()
    if status is None or getattr(status, "Status", None) != 0x0000:
        raise RuntimeError(f"gateway_c_store_failed:{getattr(status, 'Status', None)}")


def handle_store(event: evt.Event) -> int:
    ds_in = event.dataset
    ds_in.file_meta = event.file_meta

    try:
        if WORKER_DELAY_SECONDS > 0:
            time.sleep(WORKER_DELAY_SECONDS)
        result = _build_result(ds_in)
        _send_result(result)
        return 0x0000
    except Exception as exc:  # noqa: BLE001
        print(f"worker: failed to send result: {exc}", flush=True)
        return 0xA700


def main() -> None:
    ae = AE(ae_title=WORKER_AE_TITLE)
    ae.add_supported_context(CTImageStorage)
    ae.add_supported_context(MRImageStorage)
    handlers = [(evt.EVT_C_STORE, handle_store)]
    print(f"worker: listening on 0.0.0.0:{WORKER_PORT} AET={WORKER_AE_TITLE}", flush=True)
    ae.start_server(("0.0.0.0", WORKER_PORT), block=True, evt_handlers=handlers)


if __name__ == "__main__":
    main()
