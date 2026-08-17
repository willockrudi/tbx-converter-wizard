"""Read a mounted DVD's VIDEO_TS folder directly, with no ripper in the way.

Both existing rippers can refuse a disc the operating system reads perfectly
well. dvdbackup only exists on Linux, and MakeMKV declines titles whose
structure it judges unsound - which includes a title damaged by a bad burn,
even though every byte of it is readable. Between them that can leave a disc
mounted and browsable with no route into the app at all.

ffmpeg is far more tolerant than either: handed a damaged title it logs the
corrupt frames and keeps going, which is usually what you want from a disc
that is already damaged - a copy with artefacts beats no copy. Since the
mounted disc exposes the VOBs as ordinary files, no extraction step is
needed either; the encoder reads them where they lie.

Durations come from the IFO files rather than from probing the VOBs. A VOB is
a raw MPEG-2 program stream with no container index, so ffprobe's estimate
from timestamps is not merely imprecise but wrong by orders of magnitude:
summing per-VOB estimates gave 7.6 minutes for a title known to run 23:13,
and 53 hours for one running about 1:29. The IFO carries the authored
playback time as an exact field, so read that instead.
"""

from __future__ import annotations

import string
import sys
from dataclasses import dataclass
from pathlib import Path

from .discovery import Drive, DiscoveryError, Title

DVD_SECTOR = 2048

# Byte offsets within VTS_nn_0.IFO, per the DVD-Video specification as
# implemented by libdvdread (ifo_read.c).
_VTS_MAGIC = b"DVDVIDEO-VTS"
_VTS_PGCIT_PTR = 0xCC   # uint32 BE, sector offset of the PGC table
_PGCIT_HEADER = 8       # uint16 count, uint16 zero, uint32 last byte
_SRP_SIZE = 8           # per-PGC search pointer
_SRP_PGC_OFFSET = 4     # uint32 BE within the search pointer
_PGC_PLAYBACK_TIME = 4  # dvd_time_t within the PGC


def _bcd(value: int) -> int:
    return (value >> 4) * 10 + (value & 0x0F)


def parse_dvd_time(raw: bytes) -> float:
    """Decode a 4-byte dvd_time_t into seconds.

    Hours, minutes and seconds are BCD. The fourth byte packs the frame rate
    into its top two bits (3 = 30fps, 1 = 25fps) and the frame count, in BCD,
    into the low six. The frame remainder is under a second either way, so a
    missing or reserved rate code just contributes nothing rather than
    invalidating the whole reading.
    """
    if len(raw) < 4:
        raise ValueError("dvd_time_t must be 4 bytes")
    hours, minutes, seconds, frame_u = raw[0], raw[1], raw[2], raw[3]
    total = _bcd(hours) * 3600 + _bcd(minutes) * 60 + _bcd(seconds)
    rate = {3: 30.0, 1: 25.0}.get(frame_u >> 6)
    if rate:
        total += _bcd(frame_u & 0x3F) / rate
    return float(total)


def parse_ifo_durations(data: bytes) -> list[float]:
    """Every program-chain playback time in a VTS IFO, in seconds.

    Pure function over the file's bytes so it can be tested without a disc.
    Raises ValueError on anything that isn't a VTS IFO or whose offsets point
    outside the file - a damaged disc is exactly the case this module exists
    for, so a truncated IFO must fail loudly here rather than silently
    produce a title of implausible length.
    """
    if not data.startswith(_VTS_MAGIC):
        raise ValueError("not a VTS IFO (bad magic)")

    sector = int.from_bytes(data[_VTS_PGCIT_PTR:_VTS_PGCIT_PTR + 4], "big")
    base = sector * DVD_SECTOR
    if sector == 0 or base + _PGCIT_HEADER > len(data):
        raise ValueError("PGC table offset lies outside the IFO")

    count = int.from_bytes(data[base:base + 2], "big")
    durations = []
    for i in range(count):
        srp = base + _PGCIT_HEADER + i * _SRP_SIZE
        if srp + _SRP_SIZE > len(data):
            raise ValueError("PGC search pointer lies outside the IFO")
        pgc = base + int.from_bytes(
            data[srp + _SRP_PGC_OFFSET:srp + _SRP_PGC_OFFSET + 4], "big")
        if pgc + _PGC_PLAYBACK_TIME + 4 > len(data):
            raise ValueError("PGC lies outside the IFO")
        durations.append(
            parse_dvd_time(data[pgc + _PGC_PLAYBACK_TIME:pgc + _PGC_PLAYBACK_TIME + 4]))
    return durations


@dataclass
class TitleSet:
    """One VTS_nn on the disc: its number, its playback length, and the VOBs
    that carry its content (VTS_nn_0.VOB is menu data and is excluded)."""
    number: int
    length_seconds: float
    vobs: list[Path]


def _title_set_number(path: Path) -> int | None:
    stem = path.stem  # VTS_03_1
    parts = stem.split("_")
    if len(parts) != 3 or parts[0] != "VTS":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def read_title_sets(video_ts: Path) -> list[TitleSet]:
    """Enumerate the disc's title sets, longest playback time first excluded -
    order is by title number, matching how the rest of the app treats discs."""
    sets: list[TitleSet] = []
    for ifo in sorted(video_ts.glob("VTS_*_0.IFO")):
        number = _title_set_number(ifo)
        if number is None:
            continue
        # Content VOBs are VTS_nn_1.VOB upwards; VTS_nn_0.VOB holds menus.
        vobs = sorted(
            v for v in video_ts.glob(f"VTS_{number:02d}_*.VOB")
            if v.stem.rsplit("_", 1)[-1] != "0"
        )
        if not vobs or all(v.stat().st_size == 0 for v in vobs):
            continue  # an empty title set - real discs carry several
        try:
            durations = parse_ifo_durations(ifo.read_bytes())
        except (ValueError, OSError):
            durations = []
        # A title set may hold several program chains that share cells, so
        # summing would double-count; the longest chain is the feature and the
        # rest are alternate routes through the same footage.
        sets.append(TitleSet(number=number,
                             length_seconds=max(durations) if durations else 0.0,
                             vobs=vobs))
    return sets


def discover_titles(video_ts: Path) -> list[Title]:
    """discovery.discover_titles()'s shape, sourced from the mounted disc."""
    sets = read_title_sets(video_ts)
    if not sets:
        raise DiscoveryError(
            f"no readable title sets in {video_ts} - is this a DVD-Video disc?")
    return [Title(number=s.number, length_seconds=s.length_seconds) for s in sets]


def title_vobs(video_ts: Path, title_number: int) -> list[Path]:
    for s in read_title_sets(video_ts):
        if s.number == title_number:
            return s.vobs
    raise DiscoveryError(f"title {title_number} not found in {video_ts}")


def _candidate_roots() -> list[Path]:
    if sys.platform == "win32":
        # Skip A:/B: - legacy floppy letters can stall for seconds when probed.
        return [Path(f"{letter}:/") for letter in string.ascii_uppercase[2:]]
    roots: list[Path] = []
    for parent in (Path("/media"), Path("/run/media"), Path("/mnt"), Path("/Volumes")):
        if not parent.is_dir():
            continue
        try:
            for child in parent.iterdir():
                roots.append(child)
                if child.is_dir():  # /run/media/<user>/<label>
                    roots.extend(grandchild for grandchild in child.iterdir())
        except OSError:
            continue
    return roots


def find_mounted_discs() -> list[Drive]:
    """Every mounted volume carrying a VIDEO_TS folder, as Drive records so
    the GUI can list them beside the other rippers' drives. device_path is the
    VIDEO_TS path itself, which is what this module's other entry points take."""
    found: list[Drive] = []
    for root in _candidate_roots():
        try:
            video_ts = root / "VIDEO_TS"
            if not video_ts.is_dir():
                continue
        except OSError:
            continue
        found.append(Drive(
            index=len(found),
            name="Mounted DVD",
            device_path=str(video_ts),
            disc_title=root.name or str(root),
            disc_present=True,
        ))
    return found
