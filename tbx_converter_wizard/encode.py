import os
import subprocess
from pathlib import Path

from . import config


class EncodeError(RuntimeError):
    pass


def build_concat_file(vob_dir: Path, concat_path: Path) -> None:
    """Build an ffmpeg concat-demuxer list from a title's VOB files (skips menu-only _0.VOB)."""
    vobs = sorted(vob_dir.glob("VTS_*_[1-9]*.VOB"))
    if not vobs:
        raise EncodeError(f"no VOB files found in {vob_dir}")
    with concat_path.open("w") as f:
        for vob in vobs:
            f.write(f"file '{vob}'\n")


def _ffmpeg_cmd(input_args: list[str], tmp_path: Path) -> list[str]:
    profile = config.ENCODE_PROFILE
    return [
        "ffmpeg", "-y",
        *input_args,
        "-c:v", profile["video_codec"], "-crf", profile["crf"], "-preset", profile["preset"],
        "-vf", profile["scale_filter"],
        "-c:a", profile["audio_codec"], "-b:a", profile["audio_bitrate"],
        "-movflags", "+faststart",
        "-threads", "2",
        str(tmp_path),
    ]


def _encode(input_args: list[str], source_desc: str, final_path: Path) -> None:
    """Encode to the tbx_broadcast profile, writing a hidden temp name then atomically
    renaming into place — same crash-safety property as before (a half-written file
    never appears at the final name), just no longer relevant to a TBX-side scanner
    since this app has no TBX awareness at all now."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_name(f".{final_path.name}.converting.mp4")
    cmd = _ffmpeg_cmd(input_args, tmp_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError as exc:
        raise EncodeError(
            "ffmpeg not found. Install ffmpeg and make sure it's on your PATH, "
            "then restart the app."
        ) from exc
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise EncodeError(f"ffmpeg failed encoding {source_desc}: {result.stderr.strip()[-800:]}")

    os.replace(tmp_path, final_path)


def encode_concat_to_output(concat_path: Path, final_path: Path) -> None:
    """DVD-rip mode: encode a concat-demuxer VOB list to the tbx_broadcast profile."""
    _encode(["-f", "concat", "-safe", "0", "-i", str(concat_path)], str(concat_path), final_path)


def encode_file_to_output(input_path: Path, final_path: Path) -> None:
    """Convert-file mode: encode a single arbitrary local file to the tbx_broadcast profile."""
    _encode(["-i", str(input_path)], str(input_path), final_path)
