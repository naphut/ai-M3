import logging
import sys
from qt_compat import QThread, Signal, Slot, QtCore

class LogSignalEmitter(QtCore.QObject):
    log_signal = Signal(str)

class QLogHandler(logging.Handler):
    """Logging handler that safely emits log records to Qt GUI via Signal."""
    def __init__(self, callback=None):
        super().__init__()
        self.emitter = LogSignalEmitter()
        if callback:
            self.emitter.log_signal.connect(callback)

    def emit(self, record):
        try:
            log_entry = self.format(record)
            self.emitter.log_signal.emit(log_entry)
        except Exception:
            pass

def setup_logger(name="KhmerDubber", level=logging.INFO, callback=None):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Qt Signal Callback handler if provided
    if callback:
        qh = QLogHandler(callback)
        qh.setFormatter(formatter)
        logger.addHandler(qh)

    return logger

logger = setup_logger()
