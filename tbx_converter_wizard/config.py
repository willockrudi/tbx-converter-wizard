import json
import subprocess
import sys
from pathlib import Path

# Local-only app — no TBX network awareness at all. Converted files land in
# OUTPUT_DIR; getting them onto the actual TBX box is the user's own job
# (USB drive, network share, whatever). Earlier versions of this app talked
# directly to TBX's API (upload, health checks, pausing its conversion
# queue) — all deleted along with tbx_client.py once encoding moved off the
# Pi entirely: none of those problems exist when nothing runs on the Pi.

_SETTINGS_PATH = Path.home() / ".tbx_converter_wizard" / "settings.json"
_DEFAULT_OUTPUT_DIR = Path.home() / "TBX_Converted"


def _load_output_dir() -> Path:
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
        return Path(data["output_dir"])
    except Exception:
        return _DEFAULT_OUTPUT_DIR


def save_output_dir(path: Path) -> None:
    global OUTPUT_DIR
    OUTPUT_DIR = path
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps({"output_dir": str(path)}))
    except OSError:
        pass


OUTPUT_DIR = _load_output_dir()
SCRATCH_ROOT = Path.home() / ".tbx_converter_wizard" / "scratch"

# Exact "tbx_broadcast" profile, confirmed live in tbx_api/config.py.
ENCODE_PROFILE = {
    "video_codec": "libx264",
    "crf": "26",
    "preset": "faster",
    "scale_filter": "scale=-2:'min(360,ih)'",
    "audio_codec": "aac",
    "audio_bitrate": "128k",
}

DEFAULT_MIN_MINUTES = {"movie": 40, "tv": 15}

# Windows only: stop every helper we shell out to (ffmpeg, ffprobe,
# makemkvcon, dvdbackup) from opening its own console window. The packaged
# build is windowed - console=False in the PyInstaller spec - so without
# this, each spawn flashes a black box over the GUI, once per encode and
# once per probed file. 0 everywhere else; subprocess accepts
# creationflags=0 as "no special flags" on every platform, and the
# CREATE_NO_WINDOW attribute itself only exists on Windows (the ternary
# below never touches it elsewhere).
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
