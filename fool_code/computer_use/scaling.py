"""Screenshot scaling and coordinate mapping.

Image resize algorithm (imageResize) and coordinate mapping logic.

The resize algorithm uses binary search to find the largest image that:
  - preserves the input aspect ratio
  - has long edge ≤ maxTargetPx
  - has ceil(w/pxPerToken) × ceil(h/pxPerToken) ≤ maxTargetTokens

This ensures the API's vision encoder won't resize the image server-side,
keeping scaleCoord coherent with the actual image the model sees.

The ScreenshotContext stores the last screenshot's dimensions so that
coordinate-based tools can do the inverse transform.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResizeParams:
    px_per_token: int = 28
    max_target_px: int = 1568
    max_target_tokens: int = 1568


RESIZE_PARAMS = ResizeParams()


def _n_tokens_for_px(px: int, px_per_token: int) -> int:
    """ceil(px / px_per_token). Matches resize.rs:74-76."""
    return (px - 1) // px_per_token + 1


def _n_tokens_for_img(w: int, h: int, px_per_token: int) -> int:
    return _n_tokens_for_px(w, px_per_token) * _n_tokens_for_px(h, px_per_token)


def target_image_size(
    width: int,
    height: int,
    params: ResizeParams | None = None,
) -> tuple[int, int]:
    """Binary-search for the largest image that fits the token budget.

    Implements the targetImageSize algorithm.
    """
    if params is None:
        params = RESIZE_PARAMS
    ppt = params.px_per_token
    max_px = params.max_target_px
    max_tok = params.max_target_tokens

    if (
        width <= max_px
        and height <= max_px
        and _n_tokens_for_img(width, height, ppt) <= max_tok
    ):
        return width, height

    if height > width:
        w, h = target_image_size(height, width, params)
        return h, w

    aspect = width / height

    upper = width
    lower = 1

    while True:
        if lower + 1 == upper:
            return lower, max(round(lower / aspect), 1)

        mid_w = (lower + upper) // 2
        mid_h = max(round(mid_w / aspect), 1)

        if mid_w <= max_px and _n_tokens_for_img(mid_w, mid_h, ppt) <= max_tok:
            lower = mid_w
        else:
            upper = mid_w


def resize_screenshot_b64(
    b64_jpeg: str,
    screen_w: int,
    screen_h: int,
    jpeg_quality: int = 75,
) -> tuple[str, int, int]:
    """Resize a base64-encoded JPEG and return (new_b64, img_w, img_h).

    Uses a token-budget-aware algorithm. The target size is calculated
    from the *actual image dimensions* (physical pixels), not the logical
    screen dimensions. ``computeTargetDims`` passes
    ``physW = logicalW * scaleFactor`` to ``targetImageSize``.
    """
    try:
        from PIL import Image

        raw = base64.b64decode(b64_jpeg)
        img = Image.open(io.BytesIO(raw))
        actual_w, actual_h = img.size
    except ImportError:
        logger.warning("Pillow not installed — screenshot resize skipped")
        return b64_jpeg, screen_w, screen_h
    except Exception:
        logger.warning("Failed to decode image for resize")
        return b64_jpeg, screen_w, screen_h

    target_w, target_h = target_image_size(actual_w, actual_h)
    if target_w == actual_w and target_h == actual_h:
        return b64_jpeg, actual_w, actual_h

    img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return new_b64, target_w, target_h


def draw_coordinate_grid(
    b64_jpeg: str,
    img_w: int,
    img_h: int,
    grid_step: int = 100,
    jpeg_quality: int = 75,
) -> str:
    """Draw a coordinate grid overlay on a screenshot to help the model locate positions.

    Draws semi-transparent grid lines every *grid_step* pixels with coordinate
    labels at intersections.  Returns a new base64-encoded JPEG.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return b64_jpeg

    raw = base64.b64decode(b64_jpeg)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    line_color = (255, 0, 0, 60)
    text_bg = (0, 0, 0, 120)
    text_fg = (255, 255, 255, 220)

    try:
        font = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = ImageFont.load_default()

    for x in range(grid_step, img_w, grid_step):
        draw.line([(x, 0), (x, img_h)], fill=line_color, width=1)

    for y in range(grid_step, img_h, grid_step):
        draw.line([(0, y), (img_w, y)], fill=line_color, width=1)

    for x in range(grid_step, img_w, grid_step):
        for y in range(grid_step, img_h, grid_step):
            label = f"{x},{y}"
            bbox = font.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            lx = min(x + 2, img_w - tw - 2)
            ly = max(y - th - 3, 1)
            draw.rectangle([lx - 1, ly - 1, lx + tw + 1, ly + th + 1], fill=text_bg)
            draw.text((lx, ly), label, fill=text_fg, font=font)

    # axis labels along edges
    for x in range(grid_step, img_w, grid_step):
        label = str(x)
        bbox = font.getbbox(label)
        tw = bbox[2] - bbox[0]
        draw.rectangle([x + 1, 0, x + tw + 3, 13], fill=text_bg)
        draw.text((x + 2, 0), label, fill=text_fg, font=font)

    for y in range(grid_step, img_h, grid_step):
        label = str(y)
        bbox = font.getbbox(label)
        tw = bbox[2] - bbox[0]
        draw.rectangle([0, y + 1, tw + 3, y + 14], fill=text_bg)
        draw.text((1, y + 1), label, fill=text_fg, font=font)

    composite = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    composite.save(buf, format="JPEG", quality=jpeg_quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ScreenshotContext:
    """Thread-safe storage for the last screenshot's coordinate mapping.

    After a screenshot is taken (and possibly resized), store the mapping
    so that click/scroll/drag tools can transform model coordinates
    (image-pixel space) back to logical screen coordinates.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._screen_w: int = 0
        self._screen_h: int = 0
        self._image_w: int = 0
        self._image_h: int = 0

    def update(
        self,
        screen_w: int,
        screen_h: int,
        image_w: int,
        image_h: int,
    ) -> None:
        with self._lock:
            self._screen_w = screen_w
            self._screen_h = screen_h
            self._image_w = image_w
            self._image_h = image_h

    def scale_to_screen(self, img_x: int, img_y: int) -> tuple[int, int]:
        """Convert image-pixel coordinates to logical screen coordinates."""
        with self._lock:
            if self._image_w == 0 or self._image_h == 0:
                return img_x, img_y
            if self._screen_w == self._image_w and self._screen_h == self._image_h:
                return img_x, img_y
            sx = round(img_x * (self._screen_w / self._image_w))
            sy = round(img_y * (self._screen_h / self._image_h))
            return sx, sy

    def scale_to_image(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        """Convert logical screen coordinates to image-pixel coordinates."""
        with self._lock:
            if self._image_w == 0 or self._image_h == 0:
                return screen_x, screen_y
            if self._screen_w == self._image_w and self._screen_h == self._image_h:
                return screen_x, screen_y
            ix = round(screen_x * (self._image_w / self._screen_w))
            iy = round(screen_y * (self._image_h / self._screen_h))
            return ix, iy

    @property
    def info(self) -> str:
        with self._lock:
            if self._image_w == 0:
                return ""
            if self._screen_w == self._image_w:
                return f"screen={self._screen_w}x{self._screen_h}"
            return (
                f"screen={self._screen_w}x{self._screen_h}, "
                f"image={self._image_w}x{self._image_h}, "
                f"scale={self._screen_w/self._image_w:.2f}x"
            )


_ctx = ScreenshotContext()


def get_screenshot_context() -> ScreenshotContext:
    return _ctx
