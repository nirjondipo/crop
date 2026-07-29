# Crop

Desktop app for batch-resizing images into **one output folder per size**.

Every selected image is written into each size folder. Supports fit-to-width and exact crop modes, multiple sizes per job, and JPG / WebP / original format output.

## Features

- Folder or multi-file input with native file pickers
- **Fit to width** — keep aspect ratio
- **Exact crop** — crop by anchor (center, top, bottom, left, right), then resize to `W×H`
- Multiple sizes per job
- Output format: Original, JPG, or WebP
- Quality control, skip upscale, strip EXIF
- Background processing with progress, cancel, and log
- In-app **Check for updates** via [GitHub Releases](https://github.com/nirjondipo/crop/releases)

## Install (Windows)

1. Download **CropSetup.exe** from the [latest release](https://github.com/nirjondipo/crop/releases/latest)
2. Run the installer and choose an install folder
3. Optionally create a desktop shortcut
4. Open **Crop** from the Start Menu

Install location defaults to `%LOCALAPPDATA%\Crop`. Uninstall from **Settings → Apps** or the Start Menu entry.

Crop only runs when you open it — nothing starts at login.

## Usage

1. Choose **Folder** or **Files** as the source
2. Pick an output folder
3. Select mode and enter sizes
4. Choose format / quality options
5. Click **Start**

### Sizes

| Mode | Example |
|------|---------|
| Fit to width | `1920, 1280, 800` |
| Exact crop | `1920x1080, 1280x720, 800x600` |

Exact-crop folders are named like `1920x1080`.

### Output layout

```text
output/
  1920/
    photo1.webp
    photo2.webp
  800/
    photo1.webp
    photo2.webp
```

## Updates

Use **Check for updates** in the app, or download a newer **CropSetup.exe** from [Releases](https://github.com/nirjondipo/crop/releases) and run it over the existing install.

To publish a release from this repo:

```bash
git tag v1.0.1
git push origin v1.0.1
```

That triggers CI to build and attach `CropSetup.exe` to the release. Keep the tag in sync with `app/version.py`.

## Build from source

### Requirements

- Python 3.10+
- Windows (for the packaged installer), or Linux/macOS for running from source
- On Debian/Ubuntu: `python3-tk` for the GUI

### Run from source

```bash
git clone https://github.com/nirjondipo/crop.git
cd crop
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Windows installer

From the repo root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build-installer.ps1
```

Output: `dist\CropSetup.exe`

The build script can install Python / PyInstaller / Inno Setup via winget when needed.

## License

See the repository for license details.
