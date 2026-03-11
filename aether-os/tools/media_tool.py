"""media_tool — Image inspection, transformation, and basic video info.

Requires: Pillow (pip install Pillow) for image operations.
          moviepy or opencv-python for video operations (optional, gracefully skipped).
"""
from __future__ import annotations
import os, re, logging
from pathlib import Path

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).parent.parent / "agent_output" / "media"


def media_tool(
    action: str,
    source: str,
    options: str = "",
) -> str:
    """
    Work with images and media files.

    action  : info | resize | thumbnail | convert | crop | rotate | grayscale |
              flip | blur | brightness | watermark | video_info | check
    source  : Absolute or relative path to the image/video file.
    options : Comma-separated key=value pairs that action needs.
              resize     → width=800,height=600  (or just width=800 to keep ratio)
              thumbnail  → size=256             (square thumb, default 256)
              convert    → format=PNG           (PNG, JPEG, WEBP, BMP, GIF, TIFF)
              crop       → left=10,top=10,right=400,bottom=300
              rotate     → angle=90             (degrees, counter-clockwise)
              brightness → factor=1.5           (1.0 = original, >1 brighter)
              blur       → radius=2             (Gaussian blur radius)
              watermark  → text=Copyright 2025  (text to overlay)

    Actions:
        info       : Image dimensions, mode, format, file size, EXIF data.
        resize     : Resize to given width/height (preserves ratio if one dim given).
        thumbnail  : Create a square thumbnail.
        convert    : Save in a different format.
        crop       : Crop to a bounding box.
        rotate     : Rotate by given angle.
        grayscale  : Convert to grayscale.
        flip       : Flip horizontally or vertically (options: axis=h or axis=v).
        blur       : Apply Gaussian blur.
        brightness : Adjust brightness.
        watermark  : Overlay text watermark.
        video_info : Basic video metadata (requires opencv-python or moviepy).
        check      : Show which media libraries are installed.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action = action.strip().lower()

    if action == "check":
        return _check_libraries()

    if action == "video_info":
        return _video_info(source)

    # All other actions require Pillow
    try:
        from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont  # type: ignore
    except ImportError:
        return (
            "Pillow is not installed.\n"
            "Run:  pip install Pillow\n"
            "Then retry the action."
        )

    if not source or not isinstance(source, str):
        return "Error: 'source' (file path) is required."

    src = Path(source.strip())
    if not src.exists():
        return f"Error: File not found — {src}"
    if not src.is_file():
        return f"Error: Not a file — {src}"

    # Parse options
    opts = _parse_opts(options)

    if action == "info":
        return _img_info(src, Image)

    # Open image
    try:
        img: Image.Image = Image.open(src)
        img.load()
    except Exception as e:
        return f"Error opening image: {e}"

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if action == "resize":
        return _resize(img, src, opts, Image)
    if action == "thumbnail":
        return _thumbnail(img, src, opts, Image)
    if action == "convert":
        return _convert(img, src, opts)
    if action == "crop":
        return _crop(img, src, opts)
    if action == "rotate":
        return _rotate(img, src, opts)
    if action == "grayscale":
        return _grayscale(img, src)
    if action == "flip":
        return _flip(img, src, opts)
    if action == "blur":
        return _blur(img, src, opts, ImageFilter)
    if action == "brightness":
        return _brightness(img, src, opts, ImageEnhance)
    if action == "watermark":
        return _watermark(img, src, opts, ImageDraw, ImageFont)

    return (
        f"Unknown action '{action}'. Use: info, resize, thumbnail, convert, crop, "
        "rotate, grayscale, flip, blur, brightness, watermark, video_info, check."
    )


# ── image actions ─────────────────────────────────────────────────────────────

def _img_info(src: Path, Image) -> str:
    try:
        img = Image.open(src)
        img.load()
    except Exception as e:
        return f"Error opening image: {e}"
    size = src.stat().st_size
    lines = [
        f"File     : {src.name}",
        f"Path     : {src}",
        f"Format   : {img.format or 'unknown'}",
        f"Mode     : {img.mode}",
        f"Width    : {img.width} px",
        f"Height   : {img.height} px",
        f"Size     : {_human_size(size)}",
    ]
    # EXIF data
    try:
        exif_data = img._getexif()  # type: ignore
        if exif_data:
            from PIL.ExifTags import TAGS  # type: ignore
            safe_tags = {
                "Make", "Model", "DateTime", "DateTimeOriginal",
                "GPSInfo", "Orientation", "Software", "ExposureTime",
                "FNumber", "ISOSpeedRatings", "Flash",
            }
            exif_lines = []
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, str(tag_id))
                if tag in safe_tags:
                    exif_lines.append(f"  {tag}: {value}")
            if exif_lines:
                lines.append("EXIF:")
                lines += exif_lines
    except (AttributeError, Exception):
        pass
    return "\n".join(lines)


def _resize(img, src: Path, opts: dict, Image) -> str:
    w = int(opts.get("width",  0) or 0)
    h = int(opts.get("height", 0) or 0)
    if w <= 0 and h <= 0:
        return "Error: Provide width=N and/or height=N in options."
    ow, oh = img.width, img.height
    if w > 0 and h <= 0:
        h = int(oh * (w / ow))
    elif h > 0 and w <= 0:
        w = int(ow * (h / oh))
    resized = img.resize((w, h), Image.LANCZOS)
    out = _out_path(src, f"_resized_{w}x{h}")
    resized.save(str(out))
    return f"Resized {ow}×{oh} → {w}×{h}\nSaved: {out}"


def _thumbnail(img, src: Path, opts: dict, Image) -> str:
    size = int(opts.get("size", 256) or 256)
    thumb = img.copy()
    thumb.thumbnail((size, size), Image.LANCZOS)
    out = _out_path(src, f"_thumb_{size}")
    thumb.save(str(out))
    return f"Thumbnail {size}×{size} created\nSaved: {out}"


def _convert(img, src: Path, opts: dict) -> str:
    fmt = (opts.get("format") or "PNG").upper()
    allowed = {"PNG", "JPEG", "JPG", "WEBP", "BMP", "GIF", "TIFF", "ICO"}
    if fmt not in allowed:
        return f"Error: Format '{fmt}' not supported. Choose from: {', '.join(sorted(allowed))}."
    if fmt == "JPG":
        fmt = "JPEG"
    if img.mode in ("RGBA", "P") and fmt == "JPEG":
        img = img.convert("RGB")
    ext  = "jpg" if fmt == "JPEG" else fmt.lower()
    out  = _OUTPUT_DIR / (src.stem + f"_converted.{ext}")
    img.save(str(out), format=fmt)
    return f"Converted to {fmt}\nSaved: {out}"


def _crop(img, src: Path, opts: dict) -> str:
    left   = int(opts.get("left",   0))
    top    = int(opts.get("top",    0))
    right  = int(opts.get("right",  img.width))
    bottom = int(opts.get("bottom", img.height))
    if right <= left or bottom <= top:
        return "Error: Invalid crop box — right > left and bottom > top required."
    cropped = img.crop((left, top, right, bottom))
    out = _out_path(src, f"_crop_{left}_{top}_{right}_{bottom}")
    cropped.save(str(out))
    return f"Cropped to ({left},{top})-({right},{bottom})  →  {cropped.width}×{cropped.height}\nSaved: {out}"


def _rotate(img, src: Path, opts: dict) -> str:
    angle = float(opts.get("angle", 90) or 90)
    rotated = img.rotate(angle, expand=True)
    out = _out_path(src, f"_rot{int(angle)}")
    rotated.save(str(out))
    return f"Rotated {angle}°\nSaved: {out}"


def _grayscale(img, src: Path) -> str:
    gray = img.convert("L")
    out  = _out_path(src, "_gray")
    gray.save(str(out))
    return f"Converted to grayscale\nSaved: {out}"


def _flip(img, src: Path, opts: dict) -> str:
    axis = opts.get("axis", "h").lower()
    from PIL import Image  # type: ignore
    if axis in ("h", "horizontal"):
        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
        label = "horizontal"
    elif axis in ("v", "vertical"):
        flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
        label = "vertical"
    else:
        return "Error: axis must be 'h' (horizontal) or 'v' (vertical)."
    out = _out_path(src, f"_flip_{axis[0]}")
    flipped.save(str(out))
    return f"Flipped {label}\nSaved: {out}"


def _blur(img, src: Path, opts: dict, ImageFilter) -> str:
    radius = float(opts.get("radius", 2) or 2)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    out = _out_path(src, f"_blur{int(radius)}")
    blurred.save(str(out))
    return f"Gaussian blur (radius={radius}) applied\nSaved: {out}"


def _brightness(img, src: Path, opts: dict, ImageEnhance) -> str:
    factor = float(opts.get("factor", 1.5) or 1.5)
    enhanced = ImageEnhance.Brightness(img).enhance(factor)
    out = _out_path(src, f"_bright{factor:.1f}")
    enhanced.save(str(out))
    return f"Brightness adjusted (factor={factor})\nSaved: {out}"


def _watermark(img, src: Path, opts: dict, ImageDraw, ImageFont) -> str:
    text = opts.get("text", "Aether OS") or "Aether OS"
    draw = ImageDraw.Draw(img.copy())
    w, h = img.size
    # Place text at bottom-right, 10px from edge
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw_img = img.copy().convert("RGBA")
    overlay  = draw_img.copy()
    d        = ImageDraw.Draw(overlay)
    d.text((w - 200, h - 30), text, fill=(255, 255, 255, 180), font=font)
    from PIL import Image as PILImage  # type: ignore
    result = PILImage.alpha_composite(draw_img, overlay).convert(img.mode)
    out = _out_path(src, "_watermarked")
    result.save(str(out))
    return f"Watermark '{text}' added\nSaved: {out}"


# ── video info ────────────────────────────────────────────────────────────────

def _video_info(source: str) -> str:
    if not source or not isinstance(source, str):
        return "Error: 'source' (file path) is required."
    src = Path(source.strip())
    if not src.exists():
        return f"Error: File not found — {src}"

    # Try opencv first
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            return f"Error: Could not open video file — {src}"
        fps    = cap.get(cv2.CAP_PROP_FPS)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        duration = frames / fps if fps else 0
        return (
            f"File      : {src.name}\n"
            f"Size      : {_human_size(src.stat().st_size)}\n"
            f"Resolution: {width}×{height}\n"
            f"FPS       : {fps:.2f}\n"
            f"Frames    : {frames}\n"
            f"Duration  : {duration:.1f}s ({_fmt_dur(duration)})"
        )
    except ImportError:
        pass

    # Try moviepy
    try:
        from moviepy.editor import VideoFileClip  # type: ignore
        clip = VideoFileClip(str(src))
        return (
            f"File      : {src.name}\n"
            f"Size      : {_human_size(src.stat().st_size)}\n"
            f"Resolution: {clip.w}×{clip.h}\n"
            f"FPS       : {clip.fps}\n"
            f"Duration  : {clip.duration:.1f}s ({_fmt_dur(clip.duration)})"
        )
    except ImportError:
        pass

    # Fallback: just file size
    return (
        f"File : {src.name}\n"
        f"Size : {_human_size(src.stat().st_size)}\n"
        f"(Install opencv-python or moviepy for full video metadata)\n"
        f"  pip install opencv-python\n"
        f"  pip install moviepy"
    )


# ── utilities ─────────────────────────────────────────────────────────────────

def _check_libraries() -> str:
    libs = [
        ("Pillow",         "PIL",            "pip install Pillow"),
        ("opencv-python",  "cv2",            "pip install opencv-python"),
        ("moviepy",        "moviepy.editor", "pip install moviepy"),
        ("reportlab",      "reportlab",      "pip install reportlab"),
    ]
    lines = ["Media Library Status:"]
    for name, mod, install in libs:
        try:
            __import__(mod.split(".")[0])
            lines.append(f"  ✔ {name}")
        except ImportError:
            lines.append(f"  ✘ {name} — not installed  ({install})")
    lines.append(f"\nOutput directory: {_OUTPUT_DIR}")
    return "\n".join(lines)


def _parse_opts(opts: str) -> dict:
    result = {}
    if not opts or not opts.strip():
        return result
    for part in opts.split(","):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip().lower()] = v.strip()
    return result


def _out_path(src: Path, suffix: str) -> Path:
    return _OUTPUT_DIR / (src.stem + suffix + src.suffix)


def _human_size(size: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_dur(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
