"""Regression tests for output filenames going stale in the GUI.

Filenames used to be recomputed only when a mode radio was clicked or when a
file-probe thread finished - nothing watched the Title/Year/Show/Season/Episode
entries. So the natural order of operations (choose files, *then* type the
title) ran with the filenames computed before anything had been typed, and
every conversion landed as "Untitled (0).mp4". Validation passed, because by
then the fields really were filled in; only the filenames were stale.
"""
import sys
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbx_converter_wizard import gui
from tbx_converter_wizard.engine import PlannedTitle


def _tk_usable() -> bool:
    """These tests drive a real ConverterApp, so they need a display. Skipped
    rather than failed on a headless box (a bare Linux CI runner or an ssh
    session with no X), where tkinter raises TclError on Tk()."""
    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001 - tkinter raises TclError, but be broad
        return False
    root.destroy()
    return True


TK_AVAILABLE = _tk_usable()


@unittest.skipUnless(TK_AVAILABLE, "no display available for tkinter")
class TestConvertTabFilenames(unittest.TestCase):
    def setUp(self):
        self.app = gui.ConverterApp()
        self.app.withdraw()
        self.app.convert_files = [Path("clip.mkv")]
        self.app.convert_items = [PlannedTitle(title_number=0, length_seconds=600.0)]
        # Stands in for the file-probe thread finishing while the metadata
        # fields are still empty - the exact moment the stale name was baked in.
        self.app._recompute_convert()
        self.addCleanup(self.app.destroy)

    def filename(self) -> str:
        return self.app.convert_items[0].filename

    def test_blank_fields_still_fall_back_to_untitled(self):
        self.assertEqual(self.filename(), "Untitled (0).mp4")

    def test_typing_title_updates_filename(self):
        self.app.convert_title.set("Blade Runner")
        self.app.convert_year.set("1982")
        self.assertEqual(self.filename(), "Blade Runner (1982).mp4")

    def test_run_recomputes_even_if_no_trace_fired(self):
        """The traces keep the preview live, but Run must not depend on one
        having fired - paste, IME input and programmatic sets all reach the
        entries by different routes."""
        self.app.convert_title.set("Blade Runner")
        self.app.convert_year.set("1982")
        self.app.convert_items[0].filename = "STALE.mp4"
        self.app._recompute_convert()
        self.assertEqual(self.filename(), "Blade Runner (1982).mp4")

    def test_tv_mode_filename_tracks_fields(self):
        self.app.convert_mode.set("tv")
        self.app._on_convert_mode_change()
        self.app.convert_show.set("Firefly")
        self.app.convert_season.set("1")
        self.app.convert_start_episode.set("3")
        self.assertEqual(self.filename(), "Firefly S01E03.mp4")

    def test_partial_input_does_not_raise(self):
        """Recomputing on every keystroke means half-typed values hit
        int() constantly. They must be swallowed - the preview just keeps the
        last valid name, and _validate_convert_meta() still blocks Run."""
        self.app.convert_title.set("Blade Runner")
        for partial in ("", "1", "19", "198", "1982", "19a"):
            with self.subTest(year=partial):
                self.app.convert_year.set(partial)
                self.assertTrue(self.filename().endswith(".mp4"))


@unittest.skipUnless(TK_AVAILABLE, "no display available for tkinter")
@unittest.skipUnless(gui.DVD_TOOLS_AVAILABLE, "no DVD ripper installed")
class TestDriveResolution(unittest.TestCase):
    """_resolve_device() returning None is what keeps an empty or stale drive
    dropdown from reaching discover_titles_makemkv(int("")) and surfacing as a
    bare ValueError from inside the scan thread."""

    def setUp(self):
        self.app = gui.ConverterApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_empty_dropdown_resolves_to_none(self):
        self.app._drive_options = {}
        self.app.device.set("")
        self.assertIsNone(self.app._resolve_device())

    def test_stale_label_resolves_to_none(self):
        self.app._drive_options = {"D: - Some Drive": "0"}
        self.app.device.set("a label from a previous scan")
        self.assertIsNone(self.app._resolve_device())

    def test_valid_selection_resolves_to_makemkv_index(self):
        self.app._drive_options = {"D: - Some Drive (Disc)": "0"}
        self.app.device.set("D: - Some Drive (Disc)")
        self.app.ripper.set("makemkv")
        self.assertEqual(self.app._resolve_device(), "0")

    def test_message_repeats_last_scan_failure(self):
        self.app._last_drive_error = "makemkvcon failed (exit 253): too old"
        self.assertIn("exit 253", self.app._no_drive_message())


if __name__ == "__main__":
    unittest.main()
