"""Tests for reading a mounted VIDEO_TS folder directly.

The IFO fixtures are built here byte by byte rather than copied from a disc,
so the expectations are derived from the DVD-Video layout itself rather than
from whatever one sample disc happened to contain.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbx_converter_wizard import encode, videots


def _bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def make_vts_ifo(times, frame_rate_bits=3, frames=0, pgcit_sector=1) -> bytes:
    """Build a minimal but structurally valid VTS IFO carrying `times`, each
    an (hours, minutes, seconds) tuple, as one program chain apiece."""
    data = bytearray(2048 * 4)
    data[0:12] = b"DVDVIDEO-VTS"
    data[0xCC:0xD0] = pgcit_sector.to_bytes(4, "big")

    base = pgcit_sector * 2048
    data[base:base + 2] = len(times).to_bytes(2, "big")
    pgc_area = 8 + len(times) * 8  # search pointers sit between header and PGCs

    for i, (hours, minutes, seconds) in enumerate(times):
        srp = base + 8 + i * 8
        pgc_rel = pgc_area + i * 64
        data[srp + 4:srp + 8] = pgc_rel.to_bytes(4, "big")
        pgc = base + pgc_rel
        data[pgc + 4] = _bcd(hours)
        data[pgc + 5] = _bcd(minutes)
        data[pgc + 6] = _bcd(seconds)
        data[pgc + 7] = (frame_rate_bits << 6) | _bcd(frames)
    return bytes(data)


class TestParseDvdTime(unittest.TestCase):
    def test_hours_minutes_seconds_are_bcd(self):
        # 0x23 is BCD 23, not decimal 35 - reading it as hex is the classic
        # way to get a plausible-looking but wrong duration.
        raw = bytes([_bcd(1), _bcd(23), _bcd(45), 0xC0])
        self.assertEqual(videots.parse_dvd_time(raw), 3600 + 23 * 60 + 45)

    def test_ntsc_frames_add_thirtieths(self):
        raw = bytes([0x00, 0x00, _bcd(10), (3 << 6) | _bcd(15)])
        self.assertAlmostEqual(videots.parse_dvd_time(raw), 10 + 15 / 30.0)

    def test_pal_frames_add_twentyfifths(self):
        raw = bytes([0x00, 0x00, _bcd(10), (1 << 6) | _bcd(5)])
        self.assertAlmostEqual(videots.parse_dvd_time(raw), 10 + 5 / 25.0)

    def test_unknown_rate_contributes_no_frames(self):
        """A reserved rate code must not invalidate the whole reading - the
        frame remainder is under a second, the rest is still exact."""
        raw = bytes([0x00, _bcd(5), _bcd(0), (2 << 6) | _bcd(12)])
        self.assertEqual(videots.parse_dvd_time(raw), 300)

    def test_short_input_rejected(self):
        with self.assertRaises(ValueError):
            videots.parse_dvd_time(b"\x00\x00")


class TestParseIfoDurations(unittest.TestCase):
    def test_single_chain(self):
        self.assertEqual(videots.parse_ifo_durations(make_vts_ifo([(0, 23, 13)])),
                         [23 * 60 + 13])

    def test_multiple_chains(self):
        got = videots.parse_ifo_durations(make_vts_ifo([(1, 29, 5), (0, 23, 13)]))
        self.assertEqual(got, [3600 + 29 * 60 + 5, 23 * 60 + 13])

    def test_rejects_non_vts_ifo(self):
        data = bytearray(make_vts_ifo([(0, 1, 0)]))
        data[0:12] = b"DVDVIDEO-VMG"
        with self.assertRaises(ValueError):
            videots.parse_ifo_durations(bytes(data))

    def test_rejects_offset_past_end_of_file(self):
        """A truncated IFO is exactly what a damaged disc produces, and it must
        fail loudly rather than yield a title of implausible length. The
        pointer is patched after the fixture is built, so the file stays
        otherwise valid and only the offset is at fault."""
        data = bytearray(make_vts_ifo([(0, 1, 0)]))
        data[0xCC:0xD0] = (99).to_bytes(4, "big")
        with self.assertRaises(ValueError):
            videots.parse_ifo_durations(bytes(data))

    def test_rejects_zero_pgcit_pointer(self):
        data = bytearray(make_vts_ifo([(0, 1, 0)]))
        data[0xCC:0xD0] = (0).to_bytes(4, "big")
        with self.assertRaises(ValueError):
            videots.parse_ifo_durations(bytes(data))


class TestReadTitleSets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.video_ts = Path(self._tmp.name) / "VIDEO_TS"
        self.video_ts.mkdir()

    def _add_set(self, number, times, content_vobs=1, menu_vob=True):
        (self.video_ts / f"VTS_{number:02d}_0.IFO").write_bytes(make_vts_ifo(times))
        if menu_vob:
            (self.video_ts / f"VTS_{number:02d}_0.VOB").write_bytes(b"menu")
        for i in range(1, content_vobs + 1):
            (self.video_ts / f"VTS_{number:02d}_{i}.VOB").write_bytes(b"content")

    def test_reports_longest_chain_as_the_title_length(self):
        """Chains within a title set share cells, so summing double-counts;
        the longest is the feature and the others are routes through it."""
        self._add_set(1, [(0, 23, 13), (0, 5, 0)])
        sets = videots.read_title_sets(self.video_ts)
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].length_seconds, 23 * 60 + 13)

    def test_menu_vob_excluded_content_vobs_ordered(self):
        self._add_set(3, [(1, 29, 5)], content_vobs=5)
        vobs = videots.title_vobs(self.video_ts, 3)
        self.assertEqual([v.name for v in vobs],
                         [f"VTS_03_{i}.VOB" for i in range(1, 6)])

    def test_empty_title_set_skipped(self):
        """Real discs carry title sets whose content VOBs are zero bytes."""
        self._add_set(1, [(0, 10, 0)])
        (self.video_ts / "VTS_02_0.IFO").write_bytes(make_vts_ifo([(0, 0, 0)]))
        (self.video_ts / "VTS_02_1.VOB").write_bytes(b"")
        self.assertEqual([s.number for s in videots.read_title_sets(self.video_ts)], [1])

    def test_multiple_sets_reported_in_title_order(self):
        self._add_set(4, [(0, 23, 13)])
        self._add_set(3, [(1, 29, 5)])
        titles = videots.discover_titles(self.video_ts)
        self.assertEqual([t.number for t in titles], [3, 4])
        self.assertEqual([round(t.length_seconds) for t in titles],
                         [3600 + 29 * 60 + 5, 23 * 60 + 13])

    def test_damaged_ifo_yields_zero_length_not_an_exception(self):
        """A title whose IFO won't parse is still rippable - ffmpeg tolerates
        far more than the metadata does - so it must stay in the list."""
        (self.video_ts / "VTS_01_0.IFO").write_bytes(b"garbage" * 100)
        (self.video_ts / "VTS_01_1.VOB").write_bytes(b"content")
        sets = videots.read_title_sets(self.video_ts)
        self.assertEqual([(s.number, s.length_seconds) for s in sets], [(1, 0.0)])

    def test_no_titles_raises(self):
        with self.assertRaises(Exception):
            videots.discover_titles(self.video_ts)


class TestConcatFileEscaping(unittest.TestCase):
    """ffmpeg's concat demuxer treats a backslash as an escape character inside
    the quoted filename, so a Windows path is mangled before it reaches the
    filesystem. Every path must be written with forward slashes."""

    def test_backslashes_become_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "concat.txt"
            encode.write_concat_file(
                [Path(r"D:\VIDEO_TS\VTS_03_1.VOB"), Path(r"D:\VIDEO_TS\VTS_03_2.VOB")],
                out)
            text = out.read_text()
        self.assertNotIn("\\", text)
        self.assertEqual(text.splitlines()[0], "file 'D:/VIDEO_TS/VTS_03_1.VOB'")

    def test_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "concat.txt"
            names = [Path(f"/x/VTS_03_{i}.VOB") for i in (1, 2, 3)]
            encode.write_concat_file(names, out)
            lines = out.read_text().splitlines()
        self.assertEqual(lines, [f"file '/x/VTS_03_{i}.VOB'" for i in (1, 2, 3)])

    def test_empty_list_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(encode.EncodeError):
                encode.write_concat_file([], Path(tmp) / "concat.txt")


if __name__ == "__main__":
    unittest.main()
