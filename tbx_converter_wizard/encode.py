import os
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from . import config


class EncodeError(RuntimeError):
    pass


def write_concat_file(vobs: list[Path], concat_path: Path) -> None:
    """Write an ffmpeg concat-demuxer list for an explicit, ordered set of VOBs.

    Paths are written with forward slashes. ffmpeg's concat demuxer treats a
    backslash as an escape character inside the quoted filename, so a Windows
    path like D:\\VIDEO_TS\\VTS_03_1.VOB is mangled before it ever reaches the
    filesystem. Forward slashes work on Windows too, so this is just the
    portable spelling rather than a platform special case.
    """
    if not vobs:
        raise EncodeError("no VOB files to concatenate")
    lines = "".join(f"file '{str(v).replace(chr(92), '/')}'\n" for v in vobs)
    concat_path.write_text(lines, encoding="utf-8")


def build_concat_file(vob_dir: Path, concat_path: Path) -> None:
    """Build an ffmpeg concat-demuxer list from a title's VOB files (skips menu-only _0.VOB)."""
    vobs = sorted(vob_dir.glob("VTS_*_[1-9]*.VOB"))
    if not vobs:
        raise EncodeError(f"no VOB files found in {vob_dir}")
    write_concat_file(vobs, concat_path)


def _ffmpeg_cmd(input_args: list[str], tmp_path: Path) -> list[str]:
    profile = config.ENCODE_PROFILE
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        # Machine-readable progress on stdout so the GUI's log pane can show a
        # percentage instead of going silent for the entire length of a feature
        # film. stdout is free for this - the encode itself writes to a file.
        "-progress", "pipe:1",
        *input_args,
        "-c:v", profile["video_codec"], "-crf", profile["crf"], "-preset", profile["preset"],
        "-vf", profile["scale_filter"],
        "-c:a", profile["audio_codec"], "-b:a", profile["audio_bitrate"],
        "-movflags", "+faststart",
        # Deliberately no -threads cap. This was pinned to 2 back when encoding
        # ran on the Pi and had to leave headroom for live TBX playback; on the
        # user's own PC that just leaves cores idle. Let ffmpeg decide.
        str(tmp_path),
    ]


def _run_ffmpeg(cmd: list[str], log: Optional[Callable[[str], None]],
                total_seconds: float) -> tuple[int, str]:
    """Run ffmpeg, forwarding progress to `log` as it happens, and return
    (returncode, tail of stderr).

    stderr is drained on its own thread rather than read after the fact: it
    stays small with -nostats, but if it ever did fill the pipe buffer,
    ffmpeg would block on the write while we block reading stdout, and the
    whole encode would hang. That deadlock would only ever show up on a long
    encode of a file that generates lots of warnings - i.e. exactly the case
    nobody tests by hand.
    """
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", creationflags=config.NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise EncodeError(
            "ffmpeg not found. Install ffmpeg and make sure it's on your PATH, "
            "then restart the app."
        ) from exc

    stderr_tail: "deque[str]" = deque(maxlen=40)

    def drain_stderr():
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())

    drainer = threading.Thread(target=drain_stderr, daemon=True)
    drainer.start()

    last_mark = -1
    # readline rather than `for line in proc.stdout`: the latter read-aheads
    # in chunks, which would hold progress lines back until the buffer filled
    # and defeat the point of streaming them at all.
    for line in iter(proc.stdout.readline, ""):
        key, _, value = line.strip().partition("=")
        if key != "out_time_ms" or log is None:
            continue
        try:
            # ffmpeg's out_time_ms is actually microseconds - a long-standing
            # misnomer in its own -progress output, not a slip here.
            done = int(value) / 1_000_000
        except ValueError:
            continue

        if total_seconds > 0:
            mark = min(int(done / total_seconds * 100), 100)
            if mark != last_mark:
                last_mark = mark
                log(f"  {mark}%  ({done / 60:.1f} / {total_seconds / 60:.1f} min)")
        else:
            # Duration unknown (ffprobe failed, or this is a VOB concat list).
            # Report elapsed output time every 30s instead of a percentage.
            mark = int(done // 30)
            if mark != last_mark:
                last_mark = mark
                log(f"  {done / 60:.1f} min encoded")

    proc.wait()
    drainer.join(timeout=5)
    return proc.returncode, "\n".join(stderr_tail)


def _encode(input_args: list[str], source_desc: str, final_path: Path,
            log: Optional[Callable[[str], None]] = None,
            total_seconds: float = 0.0) -> None:
    """Encode to the tbx_broadcast profile, writing a hidden temp name then atomically
    renaming into place — same crash-safety property as before (a half-written file
    never appears at the final name), just no longer relevant to a TBX-side scanner
    since this app has no TBX awareness at all now."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_name(f".{final_path.name}.converting.mp4")
    cmd = _ffmpeg_cmd(input_args, tmp_path)

    returncode, stderr = _run_ffmpeg(cmd, log, total_seconds)
    if returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise EncodeError(f"ffmpeg failed encoding {source_desc}: {stderr.strip()[-800:]}")

    os.replace(tmp_path, final_path)


def encode_concat_to_output(concat_path: Path, final_path: Path,
                            log: Optional[Callable[[str], None]] = None,
                            total_seconds: float = 0.0) -> None:
    """DVD-rip mode: encode a concat-demuxer VOB list to the tbx_broadcast profile."""
    _encode(["-f", "concat", "-safe", "0", "-i", str(concat_path)], str(concat_path),
            final_path, log, total_seconds)


def encode_file_to_output(input_path: Path, final_path: Path,
                          log: Optional[Callable[[str], None]] = None,
                          total_seconds: float = 0.0) -> None:
    """Convert-file mode: encode a single arbitrary local file to the tbx_broadcast profile."""
    _encode(["-i", str(input_path)], str(input_path), final_path, log, total_seconds)
