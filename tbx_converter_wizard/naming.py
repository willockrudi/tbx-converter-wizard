import re

ILLEGAL = re.compile(r'[/\\:*?"<>|]')

# Mirrors tbx_api/importer.py's live TV-detection regex, so a naming bug here
# can never silently produce a file TBX misfiles as a movie.
TBX_TV_REGEX = re.compile(r"s\d{1,2}[._\s-]?e\d{1,2}|\d{1,2}x\d{2}|season[\s._]\d", re.IGNORECASE)


def movie_filename(title: str, year: int, suffix: str = "") -> str:
    base = f"{title} ({year})"
    if suffix:
        base += f" - {suffix}"
    return ILLEGAL.sub("", base) + ".mp4"


def episode_filename(show: str, season: int, episode: int) -> str:
    base = f"{show} S{season:02d}E{episode:02d}"
    return ILLEGAL.sub("", base) + ".mp4"


def extra_suffix(index: int) -> str:
    return f"extra {index}"
