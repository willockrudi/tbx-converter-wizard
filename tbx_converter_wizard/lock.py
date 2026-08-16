import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def held(lock_path: Path):
    """Serialize with the existing Sonarr/Radarr transcode hooks via the shared flock file."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
