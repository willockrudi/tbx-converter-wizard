import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbx_converter_wizard import discovery, rip
from tbx_converter_wizard.discovery import Drive, Title, _parse_drv_lines, _parse_hms, _parse_tinfo_lines


class TestParseDrvLines(unittest.TestCase):
    def test_single_drive_no_disc(self):
        text = 'DRV:0,2,999,12,"HL-DT-ST BD-RE  WH16NS40","","/dev/sr0"\n'
        drives = _parse_drv_lines(text)
        self.assertEqual(drives, [
            Drive(index=0, name="HL-DT-ST BD-RE  WH16NS40", device_path="/dev/sr0",
                  disc_title="", disc_present=True),
        ])

    def test_drive_with_disc_loaded(self):
        text = 'DRV:1,2,999,1,"Optical Drive","Mean Girls, Special Edition","D:"\n'
        drives = _parse_drv_lines(text)
        self.assertEqual(len(drives), 1)
        # The comma inside the quoted disc title must not split the row -
        # this is exactly why csv.reader is used instead of str.split(",").
        self.assertEqual(drives[0].disc_title, "Mean Girls, Special Edition")
        self.assertEqual(drives[0].device_path, "D:")
        self.assertTrue(drives[0].disc_present)

    def test_not_attached_drive_excluded(self):
        text = 'DRV:0,256,999,999,"","",""\n'
        self.assertEqual(_parse_drv_lines(text), [])

    def test_empty_drive_not_disc_present(self):
        text = 'DRV:0,0,999,999,"Optical Drive","","E:"\n'
        drives = _parse_drv_lines(text)
        self.assertFalse(drives[0].disc_present)

    def test_non_drv_lines_ignored(self):
        text = "MSG:1005,0,1,\"some other message\"\nDRV:0,2,999,1,\"Drive\",\"\",\"D:\"\n"
        drives = _parse_drv_lines(text)
        self.assertEqual(len(drives), 1)

    def test_malformed_line_skipped_not_raised(self):
        text = "DRV:not,enough,fields\n"
        self.assertEqual(_parse_drv_lines(text), [])


class TestParseTinfoLines(unittest.TestCase):
    def test_single_title_duration(self):
        text = "TINFO:0,9,0,\"1:32:07\"\n"
        self.assertEqual(_parse_tinfo_lines(text), [Title(number=1, length_seconds=5527.0)])

    def test_multiple_titles_sorted_and_one_indexed(self):
        text = (
            "TINFO:2,9,0,\"0:45:00\"\n"
            "TINFO:0,9,0,\"1:30:00\"\n"
            "TINFO:1,9,0,\"0:22:30\"\n"
        )
        titles = _parse_tinfo_lines(text)
        self.assertEqual([t.number for t in titles], [1, 2, 3])
        self.assertEqual(titles[0].length_seconds, 5400.0)
        self.assertEqual(titles[1].length_seconds, 1350.0)
        self.assertEqual(titles[2].length_seconds, 2700.0)

    def test_non_duration_codes_ignored(self):
        text = 'TINFO:0,27,0,"title00.mkv"\nTINFO:0,9,0,"0:10:00"\n'
        titles = _parse_tinfo_lines(text)
        self.assertEqual(titles, [Title(number=1, length_seconds=600.0)])

    def test_no_titles_returns_empty_list(self):
        self.assertEqual(_parse_tinfo_lines("MSG:1005,0,1,\"scanning\"\n"), [])


class TestMinLengthFlagConsistency(unittest.TestCase):
    """MakeMKV filters titles by its own minimum length before reporting them,
    and numbers what survives by position in that filtered list. So `info` and
    `mkv` must filter identically: scan with the flag and rip without it, and
    MakeMKV hands back a different title than the user picked, with nothing
    anywhere reporting a problem. On the disc this was found with, choosing
    the 89-minute feature would have quietly produced a 23-minute extra.
    """

    @patch("tbx_converter_wizard.discovery.find_makemkvcon", return_value="makemkvcon")
    @patch("tbx_converter_wizard.discovery.subprocess.run")
    def _info_cmd(self, mock_run, _mock_find):
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout='TINFO:0,9,0,"0:10:00"\n', stderr="")
        discovery.discover_titles_makemkv(0)
        return mock_run.call_args[0][0]

    @patch("tbx_converter_wizard.rip.discovery.find_makemkvcon", return_value="makemkvcon")
    @patch("tbx_converter_wizard.rip.subprocess.run")
    def _mkv_cmd(self, mock_run, _mock_find):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            (scratch / "title_t00.mkv").write_bytes(b"")
            rip._extract_makemkv("0", 1, scratch)
        return mock_run.call_args[0][0]

    def test_info_passes_min_length(self):
        self.assertIn(discovery.MIN_LENGTH_ARG, self._info_cmd())

    def test_mkv_passes_min_length(self):
        self.assertIn(discovery.MIN_LENGTH_ARG, self._mkv_cmd())

    def test_both_filter_identically(self):
        def minlength_args(cmd):
            return [a for a in cmd if str(a).startswith("--minlength")]

        self.assertEqual(minlength_args(self._info_cmd()), minlength_args(self._mkv_cmd()))


class TestParseHms(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_parse_hms("1:02:03"), 3723.0)

    def test_zero(self):
        self.assertEqual(_parse_hms("0:00:00"), 0.0)


if __name__ == "__main__":
    unittest.main()
