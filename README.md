# Crop — Desktop Image Batch Resizer

Python desktop app that batch-resizes images into **one folder per size**. Every image from the input folder is written into each size folder.

## Features

- Native folder pickers for input and output
- **Fit to width** — keep aspect ratio
- **Exact crop** — crop by anchor (center/top/bottom/left/right), then resize to `W×H`
- Multiple sizes per job
- Output format: Original, JPG, or WebP
- Quality slider, skip upscale, strip EXIF
- Background processing with progress, cancel, and log

## Output layout

```text
output/
  1920/
    photo1.webp
    photo2.webp
  800/
    photo1.webp
    photo2.webp
```

Exact crop sizes use folder names like `1920x1080`.

## Setup

On Ubuntu/Debian/WSL, install Tk once (required for the GUI):

```bash
sudo apt-get install -y python3-tk
```

Then:

```bash
cd ~/server/projects/crop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Web launcher (dashboard)

Open **http://localhost:1000/crop/** for **Run** / **Exit** controls.

One-time (already done if you used the install script):

```bash
bash ~/server/projects/crop/scripts/install-control-service.sh
```

This starts a small local control API (`127.0.0.1:18765`) as a systemd user service so the PHP page can open and close the desktop app.

### WSL2 display

CustomTkinter needs a working GUI display:

- **WSLg** (Windows 11): usually works out of the box
- Otherwise install/configure an X server and set `DISPLAY`

If the window does not open, check that `echo $DISPLAY` is set and a display server is running.

## Sizes input

- **Fit to width:** `1920, 1280, 800`
- **Exact crop:** `1920x1080, 1280x720, 800x600`

Each size becomes its own output folder; every image is written into every size folder.
