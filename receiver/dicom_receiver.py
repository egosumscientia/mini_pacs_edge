import threading

from pynetdicom import AE, evt
from pynetdicom.sop_class import CTImageStorage, MRImageStorage, SecondaryCaptureImageStorage

from forwarder.forwarder import Forwarder
from queue_store.queue_manager import init_db
from receiver.config import ensure_directories, load_config, log_event
from receiver.handlers import handle_echo, handle_store, set_forwarder


def start_receiver() -> None:
    config = load_config()
    ensure_directories(config)
    init_db()

    ae_title = config["edge"]["ae_title"]
    port = int(config["edge"]["port"])

    ae = AE(ae_title=ae_title)
    ae.add_supported_context(CTImageStorage)
    ae.add_supported_context(MRImageStorage)
    ae.add_supported_context(SecondaryCaptureImageStorage)

    handlers = [
        (evt.EVT_C_STORE, handle_store),
        (evt.EVT_C_ECHO, handle_echo),
    ]

    forwarder = Forwarder()
    set_forwarder(forwarder)
    if forwarder.mode != "parallel":
        threading.Thread(target=forwarder.run, daemon=True).start()

    log_event("info", "receive", study_uid=None, sop_uid=None, ae_title=ae_title, remote_ip=None, outcome="listening", error=None)
    ae.start_server(("0.0.0.0", port), block=True, evt_handlers=handlers)


if __name__ == "__main__":
    start_receiver()
