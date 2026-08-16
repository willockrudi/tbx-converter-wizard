# TBX Converter Wizard

A small desktop app with two things it can do:

- **Convert File** - pick one or more video files already on your computer,
  fill in a movie/show name, click **Run**. Each file gets encoded to TBX's
  broadcast MP4 profile and named the way TBX expects (`Title (Year).mp4` /
  `Show SxxExx.mp4`), one after another, straight into a local output folder.
- **Rip DVD** - insert a DVD you own, scan it, pick which titles to keep,
  click **Run**. Same encode profile, same output folder, just sourced from a
  disc instead of files you already have. Linux only (needs `dvdbackup`/
  `lsdvd`) - this tab disables itself automatically if those aren't present.

This app has **no network awareness of TBX at all**. It never talks to your
TBX box, never uploads anything, doesn't need an API key or your TBX's
address. Everything lands in a local folder (default `~/TBX_Converted`,
changeable from the app); getting that folder onto your actual TBX
appliance - USB drive, network share, whatever you prefer - is up to you.

Legal note (DVD ripping only): CSS decryption is technically covered by the
US DMCA's anti-circumvention clause even for personal backups of discs you
own. This is extremely common practice and rarely enforced against
individuals, but is a conscious tradeoff, not an oversight.

## One-time setup

`ffmpeg` is required for both modes. DVD ripping additionally needs
`dvdbackup`, `lsdvd`, and (for CSS-protected discs) `libdvdcss2`.

**Linux:**
```bash
sudo apt update
sudo apt install ffmpeg dvdbackup lsdvd libdvd-pkg eject
sudo dpkg-reconfigure libdvd-pkg   # builds/installs libdvdcss2 from source; accept defaults
```

**Windows:** install `ffmpeg` (e.g. `winget install ffmpeg`) and make sure
it's on your `PATH`. The Convert File tab works; Rip DVD is unavailable.

**macOS:** `brew install ffmpeg`. Convert File works; Rip DVD is unavailable.

## Running it

```bash
./run_gui.sh          # Linux/Mac
```
or `python3 -m tbx_converter_wizard.gui` directly (Windows: `python -m tbx_converter_wizard.gui`).

### Using it

1. **Convert File**: click **Choose File(s)...**, pick one or more videos.
   Set Movie or TV Show mode and fill in the name/year (or show/season/start
   episode - for TV mode, files queue up as sequential episodes starting from
   that number, in the order you selected them). Click **Run**. Progress
   streams into the log pane; each finished file lands in the output folder
   shown at the top of the window.
2. **Rip DVD** (Linux only): insert a disc, click **Scan Disc**, pick Movie/TV
   mode and fill in the name, toggle any title's **Include** cell on/off,
   click **Run**. Same output folder as Convert File. The disc auto-ejects
   when done.
3. Click **Change...** next to the output folder to pick a different
   destination - it's remembered for next time.

### MakeMKV fallback (DVD ripping only)

Most commercial DVD protection is plain CSS, which the default `dvdbackup`
path (via `libdvdcss2`) handles. If a specific disc fails to rip with
`dvdbackup` (some discs use protection beyond plain CSS - ARccOS, RipGuard,
newer CSS variants), install MakeMKV manually:

1. Download the current Linux forever-free beta build from MakeMKV's own
   site and follow its build/install instructions (`makemkv-oss` +
   `makemkv-bin`; needs a periodically-renewed free beta key -
   not handled by this app).
2. In the app, switch the **Ripper** dropdown to `makemkv` before scanning/
   burning that disc.

## Running the tests

```bash
python3 -m unittest discover -s tests
```

## How it fits into TBX

This app writes correctly-named MP4s directly matching TBX's own
`tbx_broadcast` encode profile (so TBX never needs to re-convert them) into a
local output folder - nothing more. It has no code path that reads, writes
to, or otherwise reaches a TBX box. Getting the converted files from that
local folder onto your TBX appliance's media bank is a separate, manual step
you do yourself.
