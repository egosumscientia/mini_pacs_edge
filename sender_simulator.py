import argparse
import os
import time
from typing import List

import pydicom
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


def send_files(host: str, port: int, calling_aet: str, called_aet: str, files: List[str], burst: int, delay_ms: int) -> None:
    ae = AE(ae_title=calling_aet)
    ae.add_requested_context(CTImageStorage)
    ae.add_requested_context(MRImageStorage)

    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        raise SystemExit("Association failed")

    try:
        for i in range(burst):
            for path in files:
                ds = pydicom.dcmread(path)
                status = assoc.send_c_store(ds)
                code = status.Status if status else None
                print(f"{path} burst={i+1} status={code}")
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
    finally:
        assoc.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="DICOM sender simulator")
    parser.add_argument("paths", nargs="+", help="DICOM file or directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11112)
    parser.add_argument("--calling-aet", default="SENDER")
    parser.add_argument("--called-aet", default="MINI_EDGE")
    parser.add_argument("--burst", type=int, default=1)
    parser.add_argument("--delay-ms", type=int, default=0)
    args = parser.parse_args()

    files = collect_files(args.paths)
    if not files:
        raise SystemExit("No DICOM files found")

    send_files(args.host, args.port, args.calling_aet, args.called_aet, files, args.burst, args.delay_ms)


if __name__ == "__main__":
    main()
