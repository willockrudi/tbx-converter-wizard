import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbx_converter_wizard.naming import TBX_TV_REGEX, episode_filename, movie_filename


class TestNaming(unittest.TestCase):
    def test_movie_filename(self):
        self.assertEqual(movie_filename("Robocop", 1987), "Robocop (1987).mp4")

    def test_movie_filename_extra(self):
        self.assertEqual(
            movie_filename("Robocop", 1987, "extra 1"),
            "Robocop (1987) - extra 1.mp4",
        )

    def test_movie_filename_strips_illegal_chars(self):
        self.assertEqual(movie_filename("Se7en: Redux", 1995), "Se7en Redux (1995).mp4")

    def test_episode_filename_matches_tbx_regex(self):
        fname = episode_filename("The Office", 3, 14)
        self.assertEqual(fname, "The Office S03E14.mp4")
        self.assertRegex(fname.lower(), TBX_TV_REGEX)

    def test_episode_filename_double_digit_season_and_episode(self):
        fname = episode_filename("Show", 12, 34)
        self.assertRegex(fname.lower(), TBX_TV_REGEX)


if __name__ == "__main__":
    unittest.main()
