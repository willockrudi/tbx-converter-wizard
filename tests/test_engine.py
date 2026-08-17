import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbx_converter_wizard.engine import PlannedTitle, rip_and_encode


def make_item(title_number=1, filename="Movie (2020).mp4"):
    return PlannedTitle(title_number=title_number, length_seconds=600.0, filename=filename)


class TestRipAndEncodeRipperRouting(unittest.TestCase):
    """Regression test for the bug where rip_and_encode() always built a
    VOB concat list regardless of ripper - makemkv's extract_title()
    returns a single .mkv file, not a VOB directory, so the makemkv
    ripper option never actually worked end to end before this fix."""

    @patch("tbx_converter_wizard.engine.rip.cleanup_scratch")
    @patch("tbx_converter_wizard.engine.encode.encode_file_to_output")
    @patch("tbx_converter_wizard.engine.encode.build_concat_file")
    @patch("tbx_converter_wizard.engine.rip.extract_title")
    def test_makemkv_uses_single_file_encode_path(
        self, mock_extract, mock_build_concat, mock_encode_file, mock_cleanup
    ):
        mock_extract.return_value = Path("/tmp/scratch/title00.mkv")

        rip_and_encode("0", make_item(), "makemkv", log=lambda _msg: None)

        mock_encode_file.assert_called_once()
        mock_build_concat.assert_not_called()

    @patch("tbx_converter_wizard.engine.rip.cleanup_scratch")
    @patch("tbx_converter_wizard.engine.encode.encode_concat_to_output")
    @patch("tbx_converter_wizard.engine.encode.build_concat_file")
    @patch("tbx_converter_wizard.engine.rip.extract_title")
    def test_dvdbackup_still_uses_concat_path(
        self, mock_extract, mock_build_concat, mock_encode_concat, mock_cleanup
    ):
        mock_extract.return_value = Path("/tmp/scratch/disc/VIDEO_TS")

        rip_and_encode("/dev/sr0", make_item(), "dvdbackup", log=lambda _msg: None)

        mock_build_concat.assert_called_once()
        mock_encode_concat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
