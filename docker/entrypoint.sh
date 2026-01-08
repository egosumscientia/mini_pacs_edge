#!/bin/sh
set -eu
python - <<'PY'
import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID, generate_uid

path = Path("/tmp/test.dcm")
meta = FileMetaDataset()
meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
meta.MediaStorageSOPInstanceUID = generate_uid()
meta.TransferSyntaxUID = ExplicitVRLittleEndian
meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

now = datetime.datetime.utcnow()
ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
ds.is_little_endian = True
ds.is_implicit_VR = False
ds.SOPClassUID = meta.MediaStorageSOPClassUID
ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
ds.StudyInstanceUID = generate_uid()
ds.SeriesInstanceUID = generate_uid()
ds.PatientName = "TEST^EDGE"
ds.PatientID = "EDGE001"
ds.Modality = "CT"
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
ds.save_as(str(path), write_like_original=False)
print(f"Wrote {path}")
PY
exec python /app/cli.py start
