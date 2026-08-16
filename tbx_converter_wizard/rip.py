import shutil
import subprocess
from pathlib import Path


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
    # makemkvcon titles are 0-indexed; lsdvd's are 1-indexed.
    cmd = ["makemkvcon", "mkv", f"dev:{device}", str(title_number - 1), str(scratch_dir)]
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
    subprocess.run(["eject", device], capture_output=True)
