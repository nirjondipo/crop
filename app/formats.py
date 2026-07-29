"""Format and save helpers for batch image conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

OutputFormat = Literal["original", "jpg", "webp"]

# Map Pillow format names / extensions
_EXT_TO_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}

_FORMAT_TO_EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}


def resolve_save_format(source_path: Path, output_format: OutputFormat) -> tuple[str, str]:
    """Return (Pillow format name, file extension) for saving."""
    if output_format == "jpg":
        return "JPEG", ".jpg"
    if output_format == "webp":
        return "WEBP", ".webp"

    # original
    ext = source_path.suffix.lower()
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt is None:
        # Fallback if somehow an unsupported type slipped through
        return "JPEG", ".jpg"
    return fmt, _FORMAT_TO_EXT.get(fmt, ext)


def prepare_for_save(image: Image.Image, pillow_format: str) -> Image.Image:
    """Convert mode as needed for the target format (e.g. RGBA → RGB for JPEG)."""
    if pillow_format == "JPEG":
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            return background
        if image.mode != "RGB":
            return image.convert("RGB")
    elif pillow_format == "WEBP":
        if image.mode == "P":
            return image.convert("RGBA")
    elif pillow_format == "BMP":
        if image.mode in ("RGBA", "LA", "P"):
            return image.convert("RGB")
    return image


def save_image(
    image: Image.Image,
    dest: Path,
    pillow_format: str,
    quality: int,
    strip_exif: bool,
) -> None:
    """Save image with quality and optional EXIF stripping."""
    prepared = prepare_for_save(image, pillow_format)
    kwargs: dict = {}

    if pillow_format in ("JPEG", "WEBP"):
        kwargs["quality"] = quality
        if pillow_format == "JPEG":
            kwargs["optimize"] = True
        if pillow_format == "WEBP":
            kwargs["method"] = 4

    if not strip_exif and "exif" in image.info:
        kwargs["exif"] = image.info["exif"]

    dest.parent.mkdir(parents=True, exist_ok=True)
    prepared.save(dest, pillow_format, **kwargs)


def output_filename(source: Path, ext: str, *, size_label: str | None = None) -> str:
    """Keep original basename, optional size label, apply new extension."""
    if size_label:
        return f"{source.stem}_{size_label}{ext}"
    return f"{source.stem}{ext}"
