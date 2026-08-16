# Building installers locally

```bash
pip install -r requirements.txt pyinstaller
pyinstaller packaging/tbx_converter_wizard.spec
```

Output lands in `dist/`:
- **Linux**: a single standalone executable, `dist/TBXConverterWizard`.
- **Windows** (must be built on Windows): `dist/TBXConverterWizard.exe`.
- **macOS** (must be built on macOS): `dist/TBX Converter Wizard.app`.

PyInstaller does not cross-compile — each platform's installer has to be
built on that actual platform. See `.github/workflows/build-installers.yml`
for the CI pipeline that builds all three automatically on a tagged release.

## Icons

`icons/icon.png` and `icons/icon.ico` are checked in. `icons/icon.icns`
(macOS) is *not* — it's generated at build time on the macOS CI runner from
`icon.png` via `iconutil`, since that tool only exists on macOS. To build a
`.app` locally on a Mac, generate it once yourself:

```bash
mkdir icon.iconset
sips -z 16 16   icons/icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32   icons/icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32   icons/icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64   icons/icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128 icons/icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256 icons/icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256 icons/icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512 icons/icon.png --out icon.iconset/icon_256x256@2x.png
cp icons/icon.png icon.iconset/icon_512x512.png
iconutil -c icns icon.iconset -o icons/icon.icns
rm -rf icon.iconset
```
