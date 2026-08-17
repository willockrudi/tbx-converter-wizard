# TBX Converter Wizard

A small desktop app with two things it can do:

- **Convert File** - pick one or more video files already on your computer,
  fill in a movie/show name, click **Run**. Each file gets encoded to TBX's
  broadcast MP4 profile and named the way TBX expects (`Title (Year).mp4` /
  `Show SxxExx.mp4`), one after another, straight into a local output folder.
- **Rip DVD** - insert a DVD you own, pick a drive, scan it, pick which
  titles to keep, click **Run**. Same encode profile, same output folder,
  just sourced from a disc instead of files you already have. Three rippers
  are offered: `makemkv` (any platform), `dvdbackup` (Linux only), and
  `videots`, which reads a mounted disc's `VIDEO_TS` folder using nothing but
  ffmpeg - so this tab always works, whatever else is installed.

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

`ffmpeg` is required for both modes. DVD ripping additionally needs either
MakeMKV (any platform), or on Linux, `dvdbackup` + `lsdvd` +
(for CSS-protected discs) `libdvdcss2`.

**Linux:**
```bash
sudo apt update
sudo apt install ffmpeg dvdbackup lsdvd libdvd-pkg eject
sudo dpkg-reconfigure libdvd-pkg   # builds/installs libdvdcss2 from source; accept defaults
```
MakeMKV is optional here too (see "MakeMKV" section below) - useful for
discs `dvdbackup` can't handle, or if you'd rather not build `libdvdcss2`.

**Windows:** install `ffmpeg` (e.g. `winget install ffmpeg`) and make sure
it's on your `PATH`, then install MakeMKV from
[makemkv.com](https://www.makemkv.com/) - the app looks for it on `PATH`
first, then MakeMKV's own default install locations
(`C:\Program Files (x86)\MakeMKV\` or `C:\Program Files\MakeMKV\`), so no
extra configuration is usually needed. Both Convert File and Rip DVD work;
Rip DVD only offers the MakeMKV ripper (`dvdbackup` has no Windows build).

**macOS:** `brew install ffmpeg`, then install MakeMKV from makemkv.com the
same way as Windows above. Both tabs work.

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
2. **Rip DVD**: pick a drive from the **Drive** dropdown (click
   **Refresh Drives** if you plugged one in after opening the app or just
   inserted a disc), click **Scan Disc**, pick Movie/TV mode and fill in the
   name, toggle any title's **Include** cell on/off, click **Run**. Same
   output folder as Convert File. With the `dvdbackup` ripper (Linux only)
   the disc auto-ejects when done; with `makemkv` (all platforms) you'll
   need to eject it yourself - MakeMKV doesn't expose an eject command.
3. Click **Change...** next to the output folder to pick a different
   destination - it's remembered for next time.

### MakeMKV (DVD ripping only)

MakeMKV is the only ripper that decrypts CSS on Windows/macOS, and an
alternative to `dvdbackup` on Linux for discs that use protection beyond plain CSS
(ARccOS, RipGuard, newer CSS variants, or just discs `dvdbackup` reports as
unreadable). Install it from MakeMKV's own site (Linux: build
`makemkv-oss` + `makemkv-bin` from their forever-free beta; Windows/macOS:
the regular installer). In the app, switch the **Ripper** dropdown to
`makemkv` before scanning/ripping.

### The `videots` ripper - for discs the others refuse

Set **Ripper** to `videots` when a disc is readable but the other rippers
won't produce it. It needs no tools beyond ffmpeg: the mounted disc already
exposes its VOBs as ordinary files, so it reads them where they lie, with no
extraction step and no scratch copy.

Use it when:

- **MakeMKV lists fewer titles than the disc holds.** MakeMKV declines titles
  whose structure it judges unsound, which includes a title damaged by a bad
  burn - common on DVD+R DL - even though every byte is readable. ffmpeg
  decodes the damaged frames, logs them, and keeps going, so you get a copy
  with artefacts instead of no copy at all.
- **Neither MakeMKV nor dvdbackup is installed.**

Two limits. It cannot read CSS-encrypted commercial discs, since it does no
decryption - use MakeMKV, or dvdbackup with `libdvdcss2`, for those. And it
treats each title set (`VTS_nn`) as one title, so a disc that authors several
programmes into one title set yields them joined rather than separate.

Title lengths come from the disc's IFO files, which carry the authored
playback time exactly. They are deliberately not probed from the VOBs: a VOB
is a raw MPEG-2 stream with no container index, and ffprobe's estimate on one
is wrong by orders of magnitude.

**Troubleshooting a rip that fails with an unclear error:** MakeMKV's free
build requires a periodically-renewed license key. An expired key can make
a rip fail with a `makemkvcon` error that doesn't obviously say "your key
expired." If a rip fails and the reason isn't clear from the app's log
pane, check MakeMKV's forum/site for a current key before assuming
something else is wrong.

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
