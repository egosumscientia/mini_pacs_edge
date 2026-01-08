import argparse
import os
import tempfile
import time
from datetime import datetime
from typing import List, Optional

import pydicom
import psycopg2
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID, generate_uid
from pynetdicom import AE
from pynetdicom.sop_class import CTImageStorage, MRImageStorage


def collect_files(paths: List[str]) -> List[str]:
    files: List[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                for name in names:
                    if name.lower().endswith(".dcm"):
                        files.append(os.path.join(root, name))
        else:
            files.append(path)
    return files


def _build_synthetic(path: str, patient_id: str, patient_name: str, modality: str, series_description: str) -> FileDataset:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

    now = datetime.utcnow()
    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.Modality = modality
    ds.SeriesDescription = series_description
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


def _is_valid_uid(value: str) -> bool:
    if not value or len(value) > 64:
        return False
    if value.startswith(".") or value.endswith("."):
        return False
    parts = value.split(".")
    for part in parts:
        if not part or not part.isdigit():
            return False
    return True


def _validate_uid(name: str, value: Optional[str]) -> None:
    if value is None:
        return
    if not _is_valid_uid(value):
        raise SystemExit(f"Invalid UID for {name}: {value}")


def _validate_dataset_uids(path: str, ds: pydicom.Dataset) -> None:
    study_uid = getattr(ds, "StudyInstanceUID", None)
    series_uid = getattr(ds, "SeriesInstanceUID", None)
    sop_uid = getattr(ds, "SOPInstanceUID", None)
    if not _is_valid_uid(str(study_uid or "")):
        raise SystemExit(f"Invalid StudyInstanceUID in {path}: {study_uid}")
    if not _is_valid_uid(str(series_uid or "")):
        raise SystemExit(f"Invalid SeriesInstanceUID in {path}: {series_uid}")
    if not _is_valid_uid(str(sop_uid or "")):
        raise SystemExit(f"Invalid SOPInstanceUID in {path}: {sop_uid}")

def generate_files(
    count: int,
    out_dir: Optional[str],
    patient_id: str,
    patient_name: str,
    modality: str,
    series_description: str,
) -> List[str]:
    if count <= 0:
        return []
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="mini_pacs_edge_")
    os.makedirs(out_dir, exist_ok=True)
    files: List[str] = []
    for idx in range(count):
        path = os.path.join(out_dir, f"synthetic_{idx + 1}.dcm")
        ds = _build_synthetic(path, patient_id, patient_name, modality, series_description)
        ds.save_as(path, write_like_original=False)
        files.append(path)
    return files


def _rewrite_uids(
    ds: pydicom.Dataset,
    fixed_study_uid: Optional[str],
    fixed_series_uid: Optional[str],
    fixed_sop_uid: Optional[str],
) -> pydicom.Dataset:
    study_uid = fixed_study_uid or generate_uid()
    series_uid = fixed_series_uid or generate_uid()
    sop_uid = fixed_sop_uid or generate_uid()
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid

    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.file_meta = FileMetaDataset()
    if not getattr(ds.file_meta, "TransferSyntaxUID", None):
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    if not getattr(ds.file_meta, "ImplementationClassUID", None):
        ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds.file_meta.MediaStorageSOPClassUID = getattr(ds, "SOPClassUID", ds.file_meta.get("MediaStorageSOPClassUID"))
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    return ds


def _db_params(
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
) -> dict:
    return {
        "host": db_host,
        "port": db_port,
        "dbname": db_name,
        "user": db_user,
        "password": db_password,
    }


def _apply_sequence(
    ds: pydicom.Dataset,
    sequence_value: int,
    width: int,
    patient_id: str,
    patient_name: str,
    series_description: str,
) -> None:
    suffix = f"{sequence_value:0{width}d}"
    ds.PatientID = f"{patient_id}{suffix}"
    ds.PatientName = f"{patient_name}{suffix}"
    if series_description:
        ds.SeriesDescription = f"{series_description}-{suffix}"
        ds.StudyDescription = f"{series_description}-{suffix}"


def send_files(
    host: str,
    port: int,
    calling_aet: str,
    called_aet: str,
    files: List[str],
    burst: int,
    delay_ms: int,
    rewrite_uids: bool,
    study_uid: Optional[str],
    series_uid: Optional[str],
    sop_uid: Optional[str],
    seq_from_db: bool,
    seq_width: int,
    patient_id: str,
    patient_name: str,
    series_description: str,
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    ae = AE(ae_title=calling_aet)
    ae.add_requested_context(CTImageStorage)
    ae.add_requested_context(MRImageStorage)

    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        raise SystemExit("Association failed")

    conn = None
    cur = None
    if seq_from_db:
        if study_uid or series_uid or sop_uid:
            raise SystemExit("--seq-from-db is incompatible with --study-uid/--series-uid/--sop-uid")
        conn = psycopg2.connect(**_db_params(db_host, db_port, db_name, db_user, db_password))
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("CREATE SEQUENCE IF NOT EXISTS study_name_seq")

    try:
        for i in range(burst):
            for path in files:
                ds = pydicom.dcmread(path, force=True)
                if seq_from_db:
                    cur.execute("SELECT nextval('study_name_seq')")
                    sequence_value = int(cur.fetchone()[0])
                    ds = _rewrite_uids(ds, None, None, None)
                    _apply_sequence(
                        ds,
                        sequence_value,
                        seq_width,
                        patient_id,
                        patient_name,
                        series_description,
                    )
                elif rewrite_uids:
                    ds = _rewrite_uids(ds, study_uid, series_uid, sop_uid)
                else:
                    _validate_dataset_uids(path, ds)
                status = assoc.send_c_store(ds)
                code = status.Status if status else None
                print(f"{path} burst={i+1} status={code}")
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
        assoc.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="DICOM sender simulator")
    parser.add_argument("paths", nargs="*", help="DICOM file or directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11112)
    parser.add_argument("--calling-aet", default="SENDER")
    parser.add_argument("--called-aet", default="MINI_EDGE")
    parser.add_argument("--burst", type=int, default=1)
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--generate", type=int, default=0, help="Generate N synthetic DICOM files")
    parser.add_argument("--out-dir", default=None, help="Output dir for generated DICOMs")
    parser.add_argument("--patient-id", default="EDGE001")
    parser.add_argument("--patient-name", default="TEST^EDGE")
    parser.add_argument("--modality", default="CT")
    parser.add_argument("--series-description", default="SYNTHETIC")
    parser.add_argument("--seq-from-db", action="store_true", help="Use PostgreSQL sequence for consecutive studies")
    parser.add_argument("--seq-width", type=int, default=4, help="Zero-padding width for sequence values")
    parser.add_argument("--db-host", default=os.getenv("POSTGRES_HOST", "postgres"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--db-name", default=os.getenv("POSTGRES_DB", "mini_pacs"))
    parser.add_argument("--db-user", default=os.getenv("POSTGRES_USER", "mini_pacs"))
    parser.add_argument("--db-password", default=os.getenv("POSTGRES_PASSWORD", "mini_pacs"))
    parser.add_argument("--rewrite-uids", action="store_true", help="Rewrite Study/Series/SOP UIDs per send")
    parser.add_argument("--study-uid", default=None, help="Fixed StudyInstanceUID when rewriting")
    parser.add_argument("--series-uid", default=None, help="Fixed SeriesInstanceUID when rewriting")
    parser.add_argument("--sop-uid", default=None, help="Fixed SOPInstanceUID when rewriting")
    args = parser.parse_args()

    _validate_uid("study-uid", args.study_uid)
    _validate_uid("series-uid", args.series_uid)
    _validate_uid("sop-uid", args.sop_uid)

    files = collect_files(args.paths)
    generated = generate_files(
        args.generate,
        args.out_dir,
        args.patient_id,
        args.patient_name,
        args.modality,
        args.series_description,
    )
    files.extend(generated)
    if not files:
        raise SystemExit("No DICOM files found and --generate not set")

    send_files(
        args.host,
        args.port,
        args.calling_aet,
        args.called_aet,
        files,
        args.burst,
        args.delay_ms,
        args.rewrite_uids,
        args.study_uid,
        args.series_uid,
        args.sop_uid,
        args.seq_from_db,
        args.seq_width,
        args.patient_id,
        args.patient_name,
        args.series_description,
        args.db_host,
        args.db_port,
        args.db_name,
        args.db_user,
        args.db_password,
    )


if __name__ == "__main__":
    main()
