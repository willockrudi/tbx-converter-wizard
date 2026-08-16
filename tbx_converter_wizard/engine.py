"""Shared rip/convert/encode pipeline, driven by the GUI.

No TBX network awareness — everything here writes to config.OUTPUT_DIR, a
local folder. Getting that folder onto the actual TBX box is the user's own
job. Earlier versions of this pipeline ran on the Pi itself and had to
politely share the Pi's CPU with TBX's live playback and its own background
conversion queue (a flock, an idle-wait poll, and a pause/resume API call
around every encode); none of that applies once encoding happens on the
user's own PC instead — removed rather than carried over unused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config, encode, naming, rip


class RipCancelled(Exception):
    pass


@dataclass
class PlannedTitle:
    title_number: int
    length_seconds: float
    filename: Optional[str] = None
    include: bool = True


def recompute_filenames(mode: str, items: list[PlannedTitle], **meta) -> None:
    """Assign output filenames to included items, in disc-appropriate order.
    Movie mode: longest included title is primary, rest get '- extra N'.
    TV mode: included titles sorted by on-disc title number, numbered sequentially
    from meta['start_episode'] (matches physical disc episode order)."""
    included = [it for it in items if it.include]

    if mode == "movie":
        included.sort(key=lambda it: it.length_seconds, reverse=True)
        for i, it in enumerate(included):
            suffix = "" if i == 0 else naming.extra_suffix(i)
            it.filename = naming.movie_filename(meta["title"], meta["year"], suffix)
    elif mode == "tv":
        included.sort(key=lambda it: it.title_number)
        start = meta["start_episode"]
        for i, it in enumerate(included):
            it.filename = naming.episode_filename(meta["show"], meta["season"], start + i)
    else:
        raise ValueError(f"unknown mode: {mode}")

    for it in items:
        if not it.include:
            it.filename = None


def rip_and_encode(device: str, item: PlannedTitle, ripper: str,
                    log: Callable[[str], None],
                    should_cancel: Callable[[], bool] = lambda: False) -> Path:
    if not item.filename:
        raise ValueError("planned title has no filename - call recompute_filenames first")

    run_id = uuid.uuid4().hex[:8]
    scratch_dir = config.SCRATCH_ROOT / run_id / f"title_{item.title_number:02d}"
    final_path = config.OUTPUT_DIR / item.filename

    try:
        log(f"Extracting title {item.title_number} ({item.length_seconds / 60:.1f} min)...")
        vob_dir = rip.extract_title(device, item.title_number, scratch_dir, ripper)

        if should_cancel():
            raise RipCancelled()

        concat_path = scratch_dir / "concat.txt"
        encode.build_concat_file(vob_dir, concat_path)

        if should_cancel():
            raise RipCancelled()

        log(f"Encoding -> {item.filename}")
        encode.encode_concat_to_output(concat_path, final_path)

        log(f"Done: {final_path}")
        return final_path
    finally:
        rip.cleanup_scratch(scratch_dir)


def rip_disc(device: str, items: list[PlannedTitle], ripper: str,
             log: Callable[[str], None],
             should_cancel: Callable[[], bool] = lambda: False) -> list[Path]:
    included = [it for it in items if it.include and it.filename]
    results: list[Path] = []

    for item in included:
        if should_cancel():
            log("Cancelled.")
            break
        try:
            results.append(rip_and_encode(device, item, ripper, log, should_cancel))
        except RipCancelled:
            log("Cancelled.")
            break
        except (rip.RipError, encode.EncodeError) as exc:
            log(f"FAILED: {exc}")

    rip.eject(device)
    log(f"Ejected {device}.")

    return results


def convert_file(input_path: Path, filename: str,
                  log: Callable[[str], None]) -> Path:
    """Convert-file mode: encode one arbitrary local file to the tbx_broadcast
    profile, named per TBX's conventions, dropped into config.OUTPUT_DIR."""
    final_path = config.OUTPUT_DIR / filename
    log(f"Encoding -> {filename}")
    encode.encode_file_to_output(input_path, final_path)
    log(f"Done: {final_path}")
    return final_path
