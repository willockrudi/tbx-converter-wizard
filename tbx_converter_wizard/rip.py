import shutil
import subprocess
from pathlib import Path

from . import discovery


class RipError(RuntimeError):
    pass


def extract_title(device: str, title_number: int, scratch_dir: Path, ripper: str = "dvdbackup") -> Path:
    """Extract a title's video data to scratch_dir, return the directory containing it."""
    scratch_dir.mkdir(parents=True, exist_ok=True)

    if ripper == "dvdbackup":
        return _extract_dvdbackup(device, title_number, scratch_dir)
    if ripper == "makemkv":
        return _extract_makemkv(device, title_number, scratch_dir)
    raise ValueError(f"unknown ripper: {ripper}")


def _extract_dvdbackup(device: str, title_number: int, scratch_dir: Path) -> Path:
    # -t (single title) and -M (mirror whole disc) are mutually exclusive
    # action flags in dvdbackup, not combinable - passing both makes it print
    # usage to stdout and exit 1 without touching the disc at all.
    cmd = [
        "dvdbackup", "-i", device, "-o", str(scratch_dir),
        "-t", str(title_number), "-n", "disc",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=3600)
    except FileNotFoundError as exc:
        raise RipError("dvdbackup not found - install with: sudo apt install dvdbackup") from exc

    video_ts = scratch_dir / "disc" / "VIDEO_TS"
    vobs = sorted(video_ts.glob("VTS_*_[1-9]*.VOB")) if video_ts.is_dir() else []

    if result.returncode != 0 or not vobs or all(v.stat().st_size == 0 for v in vobs):
        detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()[-500:]
        raise RipError(
            f"dvdbackup failed extracting title {title_number} (exit {result.returncode}): "
            f"{detail}\n"
            "This disc may use protection beyond plain CSS. Install MakeMKV manually "
            "(see README) and retry this title with the makemkv ripper."
        )

    return video_ts


def _extract_makemkv(device: str, title_number: int, scratch_dir: Path) -> Path:
    # device is a MakeMKV drive index here (see discovery.list_makemkv_drives()),
    # not an OS device path - disc:<index> is MakeMKV's own addressing, which
    # works identically cross-platform (unlike a raw /dev/sr0-style path).
    # makemkvcon titles are 0-indexed; discovery.discover_titles_makemkv()
    # converts to 1-indexed to match lsdvd's convention, so undo that here.
    makemkvcon = discovery.find_makemkvcon()
    if makemkvcon is None:
        raise RipError("makemkvcon not found - MakeMKV must be installed manually, see README")

    cmd = [makemkvcon, "mkv", f"disc:{device}", str(title_number - 1), str(scratch_dir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=3600)
    except FileNotFoundError as exc:
        raise RipError(
            "makemkvcon not found - MakeMKV must be installed manually, see README"
        ) from exc

    mkvs = sorted(scratch_dir.glob("*.mkv"))
    if result.returncode != 0 or not mkvs:
        raise RipError(
            f"makemkvcon failed extracting title {title_number} (exit {result.returncode}): "
            f"{result.stderr.strip()[-500:]}"
        )

    return mkvs[0]


def cleanup_scratch(scratch_dir: Path) -> None:
    shutil.rmtree(scratch_dir, ignore_errors=True)


def eject(device: str) -> None:
    """Best-effort only - a missing `eject` binary (or any other OSError)
    must not blow up the caller. Previously uncaught here, this would
    propagate out of engine.rip_disc() and get caught by gui.py's
    outermost exception handler, which logged the whole rip - including
    already-successful titles - as "Rip failed unexpectedly". Only ever
    called for the dvdbackup ripper (see engine.rip_disc()), so `device`
    here is always a real OS device path, never a MakeMKV drive index."""
    try:
        subprocess.run(["eject", device], capture_output=True)
    except OSError:
        pass
