import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass


class DiscoveryError(RuntimeError):
    pass


@dataclass
class Title:
    number: int
    length_seconds: float


def discover_titles(device: str) -> list[Title]:
    try:
        result = subprocess.run(
            ["lsdvd", "-x", "-Ox", device],
            capture_output=True, text=True, errors="replace", timeout=60,
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
