import csv
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import config


class DiscoveryError(RuntimeError):
    pass


@dataclass
class Title:
    number: int
    length_seconds: float


@dataclass
class Drive:
    """One optical drive, as MakeMKV itself sees it - index is MakeMKV's
    own drive index, reused verbatim by discover_titles_makemkv() and
    rip.py's _extract_makemkv() for both info and mkv commands."""
    index: int
    name: str
    device_path: str
    disc_title: str = ""
    disc_present: bool = False


# MakeMKV's Windows installer doesn't add itself to PATH by default -
# these are its own default install locations, checked as a fallback.
_WINDOWS_MAKEMKV_DIRS = (
    r"C:\Program Files (x86)\MakeMKV",
    r"C:\Program Files\MakeMKV",
)


def find_makemkvcon() -> str | None:
    """Locate makemkvcon(64).exe - PATH first, then (on Windows) MakeMKV's
    own default install directories. Shared by discovery.py and rip.py so
    the search logic lives in exactly one place."""
    for name in ("makemkvcon64.exe", "makemkvcon.exe", "makemkvcon"):
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        for base in _WINDOWS_MAKEMKV_DIRS:
            for name in ("makemkvcon64.exe", "makemkvcon.exe"):
                candidate = Path(base) / name
                if candidate.is_file():
                    return str(candidate)
    return None


def discover_titles(device: str) -> list[Title]:
    try:
        result = subprocess.run(
            ["lsdvd", "-x", "-Ox", device],
            capture_output=True, text=True, errors="replace", timeout=60,
            creationflags=config.NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise DiscoveryError("lsdvd not found - install with: sudo apt install lsdvd") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiscoveryError(f"lsdvd timed out reading {device} - is a disc inserted?") from exc

    if result.returncode != 0:
        raise DiscoveryError(f"lsdvd failed on {device}: {result.stderr.strip()}")

    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError as exc:
        raise DiscoveryError(f"could not parse lsdvd output: {exc}") from exc

    titles = []
    for track in root.findall("track"):
        ix = track.find("ix")
        length = track.find("length")
        if ix is None or length is None:
            continue
        titles.append(Title(number=int(ix.text), length_seconds=float(length.text)))

    if not titles:
        raise DiscoveryError(f"no titles found on {device} - blank, unreadable, or no disc inserted")

    return titles


# ── MakeMKV-based discovery (cross-platform - Windows and Linux alike) ─────

# DRV: line status codes, per MakeMKV's robot-mode output.
_DRV_STATUS_NOT_ATTACHED = 256
_DRV_STATUS_DISC_PRESENT = (2, 3)  # closed (has disc) / loading

# MakeMKV title scans are slow, and the old 60s ceiling was well under what a
# real disc takes: a single 23-minute title on a healthy home-burned DVD+R-DL
# measured 76s on a USB drive - and that is close to a best case. Commercial
# discs have many more titles, CSS to work through, and often trigger the
# drive's region workaround, all of which add minutes. Worse, blowing the
# timeout raised "is a disc inserted?", which blamed the user for the one
# thing that was definitely fine.
_DRIVE_SCAN_TIMEOUT = 120
_TITLE_SCAN_TIMEOUT = 900

# MakeMKV applies its own minimum-title-length filter before it reports
# anything. On a real test disc that silently hid the 89-minute main feature
# while still listing a 23-minute extra, so the disc looked like it held
# nothing but a short clip. This app already has a length filter of its own -
# the "Min length to include" box - and it can only filter what it is told
# about, so MakeMKV must hand over everything and let the app decide.
#
# This MUST be passed identically to `info` and `mkv`. MakeMKV numbers titles
# by position in the *filtered* list, so scanning with this flag and ripping
# without it silently rips a different title than the one selected: on that
# same disc, picking the 89-minute feature would have produced the 23-minute
# extra instead, with nothing anywhere reporting a problem.
MIN_LENGTH_ARG = "--minlength=0"


def list_makemkv_drives() -> list[Drive]:
    """Enumerate optical drives via MakeMKV's own robot-mode scan - this
    is what replaces Windows-native drive enumeration (no ctypes/wmi/
    win32api needed): MakeMKV already knows how to list every optical
    drive on the system, on any platform, including drive letters."""
    makemkvcon = find_makemkvcon()
    if makemkvcon is None:
        raise DiscoveryError("makemkvcon not found - install MakeMKV, see README")
    try:
        result = subprocess.run(
            [makemkvcon, "-r", "--cache=1", "info", "disc:9999"],
            capture_output=True, text=True, errors="replace",
            timeout=_DRIVE_SCAN_TIMEOUT, creationflags=config.NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise DiscoveryError("makemkvcon not found - install MakeMKV, see README") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiscoveryError(
            f"makemkvcon timed out after {_DRIVE_SCAN_TIMEOUT}s scanning for drives. "
            "A USB optical drive that has gone to sleep can take a while to spin up - "
            "try again."
        ) from exc

    # Previously unchecked here - a nonzero exit (e.g. MakeMKV's license
    # agreement not yet accepted, which it prompts for on first run) meant
    # this silently returned an empty list with no feedback anywhere, which
    # looks identical in the UI to "no drive was found" - drop the same
    # returncode check discover_titles() already does for lsdvd.
    if result.returncode != 0:
        detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()[-500:]
        raise DiscoveryError(f"makemkvcon failed scanning for drives (exit {result.returncode}): {detail}")

    drives = _parse_drv_lines(result.stdout)
    if not drives:
        detail = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()[-500:]
        raise DiscoveryError(
            "makemkvcon ran but found no optical drives - is one connected, and does "
            f"Windows itself see it? Raw output:\n{detail}"
        )
    return drives


def _parse_drv_lines(text: str) -> list[Drive]:
    """Pure parsing, factored out from list_makemkv_drives() so it's
    testable against canned text without a real drive/subprocess.

    DRV: line shape (7 fields): index, status, a constant, disc-type
    flags, drive/model name, media title label (empty if no disc), OS
    device/drive-letter path. Fields may be quoted (model/media names can
    contain commas) - csv.reader, not a naive .split(","), handles that.
    """
    drives = []
    for line in text.splitlines():
        if not line.startswith("DRV:"):
            continue
        fields = next(csv.reader([line[len("DRV:"):]]))
        if len(fields) < 7:
            continue
        try:
            index, status = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if status == _DRV_STATUS_NOT_ATTACHED:
            continue
        drives.append(Drive(
            index=index,
            name=fields[4],
            device_path=fields[6],
            disc_title=fields[5],
            disc_present=status in _DRV_STATUS_DISC_PRESENT,
        ))
    return drives


def discover_titles_makemkv(drive_index: int) -> list[Title]:
    """MakeMKV equivalent of discover_titles() - same Title(number,
    length_seconds) shape, sourced from `makemkvcon info` instead of
    lsdvd. drive_index comes from list_makemkv_drives()."""
    makemkvcon = find_makemkvcon()
    if makemkvcon is None:
        raise DiscoveryError("makemkvcon not found - install MakeMKV, see README")
    try:
        result = subprocess.run(
            [makemkvcon, "-r", MIN_LENGTH_ARG, "info", f"disc:{drive_index}"],
            capture_output=True, text=True, errors="replace",
            timeout=_TITLE_SCAN_TIMEOUT, creationflags=config.NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise DiscoveryError("makemkvcon not found - install MakeMKV, see README") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiscoveryError(
            f"makemkvcon timed out after {_TITLE_SCAN_TIMEOUT}s reading drive "
            f"{drive_index}. Scanning a disc routinely takes a minute or two; a "
            "scratched or dirty one can take far longer or stall outright. Try "
            "cleaning the disc, or another drive."
        ) from exc

    titles = _parse_tinfo_lines(result.stdout)
    if not titles:
        raise DiscoveryError(f"no titles found on drive {drive_index} - blank, unreadable, or no disc inserted")
    return titles


def _parse_tinfo_lines(text: str) -> list[Title]:
    """Pure parsing, factored out for testing. TINFO:title_id,code,value -
    code 9 is duration (H:MM:SS). MakeMKV title ids are 0-indexed;
    converted to 1-indexed here to match lsdvd's convention, which the
    rest of the app (naming.py, movie/TV sort order, the GUI's Title#
    column) already assumes everywhere - rip.py's _extract_makemkv()
    already does the inverse conversion back to 0-indexed."""
    TINFO_DURATION_CODE = 9
    lengths: dict[int, float] = {}
    for line in text.splitlines():
        if not line.startswith("TINFO:"):
            continue
        fields = next(csv.reader([line[len("TINFO:"):]]))
        if len(fields) < 3:
            continue
        try:
            title_id, code = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if code == TINFO_DURATION_CODE:
            try:
                lengths[title_id] = _parse_hms(fields[-1])
            except ValueError:
                continue
    return [Title(number=tid + 1, length_seconds=secs) for tid, secs in sorted(lengths.items())]


def _parse_hms(value: str) -> float:
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
