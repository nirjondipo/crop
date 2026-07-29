"""Batch image scan, resize/crop, and per-size folder output."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from PIL import Image

from app.formats import OutputFormat, output_filename, resolve_save_format, save_image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

ResizeMode = Literal["fit_width", "exact_crop"]
CropAnchor = Literal["center", "top", "bottom", "left", "right"]

# Pillow is release-friendly; keep pool modest on WSL
_MAX_WORKERS = 4


@dataclass
class SizeSpec:
    """A target size. For fit_width, height is ignored (None)."""

    width: int
    height: int | None = None

    def folder_name(self, mode: ResizeMode) -> str:
        if mode == "fit_width" or self.height is None:
            return str(self.width)
        return f"{self.width}x{self.height}"


@dataclass
class JobSettings:
    output_folder: Path
    mode: ResizeMode
    sizes: list[SizeSpec]
    format: OutputFormat
    input_folder: Path | None = None
    input_files: list[Path] | None = None
    quality: int = 80
    crop_anchor: CropAnchor = "center"
    skip_upscale: bool = True
    strip_exif: bool = True
    include_subfolders: bool = False


def resolve_input_images(settings: JobSettings) -> list[Path]:
    """Images from an explicit file list, or by scanning a folder."""
    if settings.input_files:
        out: list[Path] = []
        for path in settings.input_files:
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                out.append(path)
        return out
    if settings.input_folder is not None:
        return scan_images(settings.input_folder, settings.include_subfolders)
    return []


@dataclass
class ProgressEvent:
    current: int
    total: int
    filename: str
    message: str
    level: Literal["info", "ok", "skip", "error"] = "info"
    errors: int = 0
    done: bool = False


ProgressCallback = Callable[[ProgressEvent], None]


def scan_images(folder: Path, include_subfolders: bool = False) -> list[Path]:
    """Collect supported image paths (sorted by name)."""
    if not folder.is_dir():
        return []

    files: list[Path] = []
    if include_subfolders:
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                files.append(path)
    else:
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                files.append(path)

    return sorted(files, key=lambda p: p.name.lower())


def _crop_box(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    anchor: CropAnchor,
) -> tuple[int, int, int, int]:
    """Compute crop rectangle that covers target aspect ratio."""
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_h = src_h
        crop_w = int(round(src_h * target_ratio))
    else:
        crop_w = src_w
        crop_h = int(round(src_w / target_ratio))

    if anchor == "center":
        left = (src_w - crop_w) // 2
        top = (src_h - crop_h) // 2
    elif anchor == "top":
        left = (src_w - crop_w) // 2
        top = 0
    elif anchor == "bottom":
        left = (src_w - crop_w) // 2
        top = src_h - crop_h
    elif anchor == "left":
        left = 0
        top = (src_h - crop_h) // 2
    else:  # right
        left = src_w - crop_w
        top = (src_h - crop_h) // 2

    return left, top, left + crop_w, top + crop_h


def fit_to_width(image: Image.Image, target_width: int, skip_upscale: bool) -> Image.Image:
    w, h = image.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid image dimensions")
    if skip_upscale and w <= target_width:
        return image.copy()
    new_h = max(1, round(h * target_width / w))
    return image.resize((target_width, new_h), Image.Resampling.LANCZOS)


def exact_crop(
    image: Image.Image,
    target_w: int,
    target_h: int,
    anchor: CropAnchor,
    skip_upscale: bool,
) -> Image.Image:
    w, h = image.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid image dimensions")

    box = _crop_box(w, h, target_w, target_h, anchor)
    cropped = image.crop(box)
    cw, ch = cropped.size

    if skip_upscale and cw <= target_w and ch <= target_h:
        if cw == target_w and ch == target_h:
            return cropped
        if cw < target_w or ch < target_h:
            return cropped

    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _transform(
    img: Image.Image,
    size: SizeSpec,
    settings: JobSettings,
) -> Image.Image:
    if settings.mode == "fit_width":
        return fit_to_width(img, size.width, settings.skip_upscale)
    if size.height is None:
        raise ValueError(f"Exact crop requires height for size {size.width}")
    return exact_crop(
        img,
        size.width,
        size.height,
        settings.crop_anchor,
        settings.skip_upscale,
    )


def process_one(
    source: Path,
    dest_dir: Path,
    size: SizeSpec,
    settings: JobSettings,
    image: Image.Image | None = None,
) -> Path:
    """Process a single image into one size folder. Returns destination path."""

    def _save(img: Image.Image) -> Path:
        result = _transform(img, size, settings)
        pillow_format, ext = resolve_save_format(source, settings.format)
        dest = dest_dir / output_filename(source, ext)
        save_image(result, dest, pillow_format, settings.quality, settings.strip_exif)
        return dest

    if image is not None:
        return _save(image)

    with Image.open(source) as img:
        img.load()
        return _save(img)


def process_image_all_sizes(source: Path, settings: JobSettings) -> list[tuple[SizeSpec, Exception | None]]:
    """Open once; write every size. Returns per-size errors (None = ok)."""
    results: list[tuple[SizeSpec, Exception | None]] = []
    with Image.open(source) as img:
        img.load()
        for size in settings.sizes:
            size_dir = settings.output_folder / size.folder_name(settings.mode)
            try:
                process_one(source, size_dir, size, settings, image=img)
                results.append((size, None))
            except Exception as exc:  # noqa: BLE001
                results.append((size, exc))
    return results


@dataclass
class BatchRunner:
    settings: JobSettings
    on_progress: ProgressCallback
    _cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _current: int = 0
    _errors: int = 0

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        images = resolve_input_images(self.settings)
        sizes = self.settings.sizes
        if not images:
            self.on_progress(
                ProgressEvent(0, 0, "", "No images found.", "error", 0, True)
            )
            return
        if not sizes:
            self.on_progress(
                ProgressEvent(0, 0, "", "No sizes configured.", "error", 0, True)
            )
            return

        for size in sizes:
            (self.settings.output_folder / size.folder_name(self.settings.mode)).mkdir(
                parents=True, exist_ok=True
            )

        total = len(images) * len(sizes)
        self._current = 0
        self._errors = 0

        self.on_progress(
            ProgressEvent(
                0,
                total,
                "",
                f"Found {len(images)} image(s), {len(sizes)} size(s) → {total} file(s).",
                "info",
                0,
                False,
            )
        )

        workers = min(_MAX_WORKERS, max(1, len(images)))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._safe_process, source): source for source in images
            }
            for future in as_completed(futures):
                if self._cancel.is_set():
                    for f in futures:
                        f.cancel()
                    with self._lock:
                        current, errors = self._current, self._errors
                    self.on_progress(
                        ProgressEvent(
                            current,
                            total,
                            "",
                            "Cancelled.",
                            "skip",
                            errors,
                            True,
                        )
                    )
                    return

                source = futures[future]
                try:
                    size_results = future.result()
                except Exception as exc:  # noqa: BLE001
                    with self._lock:
                        self._current += len(sizes)
                        self._errors += len(sizes)
                        current, errors = self._current, self._errors
                    self.on_progress(
                        ProgressEvent(
                            current,
                            total,
                            source.name,
                            f"Error: {exc}",
                            "error",
                            errors,
                            False,
                        )
                    )
                    continue

                for size, err in size_results:
                    with self._lock:
                        self._current += 1
                        if err is not None:
                            self._errors += 1
                        current, errors = self._current, self._errors
                    if err is not None:
                        self.on_progress(
                            ProgressEvent(
                                current,
                                total,
                                source.name,
                                f"Error ({size.folder_name(self.settings.mode)}): {err}",
                                "error",
                                errors,
                                False,
                            )
                        )
                    else:
                        # Lightweight ok tick — UI throttles these
                        self.on_progress(
                            ProgressEvent(
                                current,
                                total,
                                source.name,
                                "",
                                "ok",
                                errors,
                                False,
                            )
                        )

        with self._lock:
            current, errors = self._current, self._errors

        self.on_progress(
            ProgressEvent(
                current,
                total,
                "",
                f"Done. {current - errors}/{total} ok, {errors} error(s).",
                "info",
                errors,
                True,
            )
        )

    def _safe_process(self, source: Path) -> list[tuple[SizeSpec, Exception | None]]:
        if self._cancel.is_set():
            return [(s, RuntimeError("Cancelled")) for s in self.settings.sizes]
        return process_image_all_sizes(source, self.settings)
