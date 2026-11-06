# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "pillow", "svgelements"]
# ///
"""Paints the homepage's illustration, static/town.webp, from the layouts in town.svg and sky.svg: a watercolor wash and an inked line for each of their shapes, on paper. Run it with `uv run art/paint.py` after changing them."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from svgelements import SVG, Shape, Text
from svgelements import Path as SvgPath

HERE = Path(__file__).parent
WIDTH = 2000
SCALE = WIDTH / 1400
SKY_TOP = 40  # where sky.svg starts, in SVG units
TOWN_TOP = 300  # where town.svg starts, in SVG units
HEIGHT = int((TOWN_TOP + 460) * SCALE)
INK = np.array([0.17, 0.13, 0.10])
SUPERSAMPLE = 2
# the top of the sky, which home.css matches so that the image blends into taller containers
SKY = "#8fd3f7"

rng = np.random.default_rng(7)


def noise(cell: int):
    """Smooth noise over the whole canvas, from -1 to 1, with features about `cell` pixels across."""
    small = rng.random((HEIGHT // cell + 3, WIDTH // cell + 3), dtype=np.float32)
    image = Image.fromarray(small, "F").resize(
        (WIDTH, HEIGHT), Image.Resampling.BICUBIC
    )
    values = np.asarray(image)
    return np.clip((values - values.mean()) / (values.std() * 2.5), -1, 1)


EDGE = noise(9) * 0.6 + noise(3) * 0.4
WASH = noise(70) * 0.6 + noise(22) * 0.4
GRAIN = noise(2) * 0.7 + np.clip(rng.normal(0, 0.5, (HEIGHT, WIDTH)), -1, 1) * 0.3


def blur(mask: np.ndarray, radius: float):
    image = Image.fromarray((mask * 255).astype(np.uint8), "L")
    return (
        np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)
        / 255
    )


def rgb(color):
    return np.array([color.red, color.green, color.blue], dtype=np.float32) / 255


def lines_of(path: SvgPath):
    """Each subpath of the path, as an array of points."""
    lines = []
    for sub in path.as_subpaths():
        sub = SvgPath(sub)
        if sub.length() == 0:
            continue
        count = max(int(sub.length() / 1.5), 6)
        points = sub.npoint(np.linspace(0, 1, count))
        lines.append(points)
    return lines


def crop_of(lines: list[np.ndarray], margin: int):
    """The canvas slices around the lines, with their left and top."""
    points = np.concatenate(lines)
    left = max(int(points[:, 0].min()) - margin, 0)
    top = max(int(points[:, 1].min()) - margin, 0)
    right = min(int(points[:, 0].max()) + margin, WIDTH)
    bottom = min(int(points[:, 1].max()) + margin, HEIGHT)
    return left, top, right, bottom


def wash(canvas: np.ndarray, lines: list[np.ndarray], color: np.ndarray):
    """Lays down a wash, which bleeds at its edges and pools pigment along them."""
    left, top, right, bottom = crop_of(lines, 16)
    if right <= left or bottom <= top:
        return
    size = (right - left) * SUPERSAMPLE, (bottom - top) * SUPERSAMPLE
    image = Image.new("L", size)
    draw = ImageDraw.Draw(image)
    for line in lines:
        points = (line - (left, top)) * SUPERSAMPLE
        if len(points) > 2:
            draw.polygon([tuple(p) for p in points], fill=255)
    mask = (
        np.asarray(
            image.resize((right - left, bottom - top), Image.Resampling.BOX),
            dtype=np.float32,
        )
        / 255
    )

    region = (slice(top, bottom), slice(left, right))
    soft = blur(mask, 1.6)
    shape = np.clip((soft - 0.5 + 0.2 * EDGE[region]) * 5 + 0.5, 0, 1)
    pooled = np.clip(shape - blur(shape, 6), 0, 1)
    pigment = (
        color[None, None] * (1 + 0.07 * WASH[region] + 0.03 * GRAIN[region])[..., None]
    )
    pigment = pigment * (1 - 0.4 * pooled)[..., None]
    alpha = (shape * (0.9 + 0.08 * WASH[region]))[..., None]
    canvas[region] = canvas[region] * (1 - alpha) + np.clip(pigment, 0, 1) * alpha


def dashes(line: np.ndarray, on: float, off: float):
    """The pieces of the line that are drawn when it's dashed."""
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    distance = np.concatenate([[0], np.cumsum(steps)])
    phase = distance % (on + off) < on
    pieces = np.split(line, np.flatnonzero(np.diff(phase.astype(int))) + 1)
    return [
        p
        for p, start in zip(
            pieces, np.split(phase, np.flatnonzero(np.diff(phase.astype(int))) + 1)
        )
        if start[0]
    ]


def ink(canvas: np.ndarray, lines: list[np.ndarray], color: np.ndarray, width: float):
    """Draws the lines with a shaky hand, swelling and thinning as a brush pen does."""
    left, top, right, bottom = crop_of(lines, int(width) + 8)
    if right <= left or bottom <= top:
        return
    size = (right - left) * SUPERSAMPLE, (bottom - top) * SUPERSAMPLE
    image = Image.new("L", size)
    draw = ImageDraw.Draw(image)
    for line in lines:
        count = len(line)
        drift = np.cumsum(rng.normal(0, 0.12, (count, 2)), axis=0)
        # pulled back to zero by the end, so that closed shapes still meet
        drift -= np.linspace(0, 1, count)[:, None] * drift[-1]
        swell = 0.8 + 0.3 * np.sin(
            np.linspace(0, rng.uniform(4, 16), count) + rng.uniform(0, 6)
        )
        points = (line + drift - (left, top)) * SUPERSAMPLE
        for (x, y), s in zip(points, swell):
            radius = max(width * s * SUPERSAMPLE / 2, 0.6)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    mask = (
        np.asarray(
            image.resize((right - left, bottom - top), Image.Resampling.BOX),
            dtype=np.float32,
        )
        / 255
    )
    region = (slice(top, bottom), slice(left, right))
    alpha = (mask * (0.86 + 0.14 * GRAIN[region]))[..., None]
    canvas[region] = canvas[region] * (1 - alpha) + color * alpha


def letter(canvas: np.ndarray, element: Text, offset: float):
    """Hand-letters a sign."""
    size = int(element.font_size * SCALE * 1.15)
    for font_path in (
        "/System/Library/Fonts/MarkerFelt.ttc",
        "/System/Library/Fonts/Supplemental/Comic Sans MS.ttf",
    ):
        try:
            font = ImageFont.truetype(font_path, size * SUPERSAMPLE)
            break
        except OSError:
            continue
    else:
        font = ImageFont.load_default(size * SUPERSAMPLE)
    x, y = element.x * SCALE, (element.y + offset) * SCALE
    width, height = int(size * len(element.text) * 0.8) + 8, size * 2
    left, top = int(x - width / 2), int(y - height * 0.75)
    image = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE))
    ImageDraw.Draw(image).text(
        ((x - left) * SUPERSAMPLE, (y - top) * SUPERSAMPLE),
        element.text,
        fill=255,
        font=font,
        anchor="ms",
    )
    mask = (
        np.asarray(
            image.resize((width, height), Image.Resampling.BOX), dtype=np.float32
        )
        / 255
    )
    region = (slice(top, top + height), slice(left, left + width))
    alpha = (mask * 0.9)[..., None]
    canvas[region] = canvas[region] * (1 - alpha) + INK * alpha


def paint(canvas: np.ndarray, name: str, offset: float):
    for element in SVG.parse(HERE / name, reify=True).elements():
        if isinstance(element, Text):
            letter(canvas, element, offset)
        if not isinstance(element, Shape) or isinstance(element, Text):
            continue
        path = SvgPath(element)
        if len(path) == 0:
            continue
        lines = [(line + (0, offset)) * SCALE for line in lines_of(path)]
        if not lines:
            continue
        if element.fill is not None and element.fill.value is not None:
            wash(canvas, lines, rgb(element.fill))
        if element.stroke is not None and element.stroke.value is not None:
            width = element.stroke_width * SCALE * 0.75
            dash = element.values.get("stroke-dasharray")
            if dash:
                on, off = (float(n) * SCALE for n in dash.split())
                lines = [piece for line in lines for piece in dashes(line, on, off)]
            ink(canvas, lines, rgb(element.stroke), width)


def main():
    top = np.array(Image.new("RGB", (1, 1), SKY), dtype=np.float32)[0, 0] / 255
    bottom = np.array(Image.new("RGB", (1, 1), "#e4f6fb"), dtype=np.float32)[0, 0] / 255
    depth = np.clip(np.linspace(0, 1, HEIGHT) ** 1.2, 0, 1)[:, None, None]
    canvas = np.tile(top * (1 - depth) + bottom * depth, (1, WIDTH, 1)).astype(
        np.float32
    )
    # blotchy, as washes dry, but flat at the very top so that it blends into its container
    blotches = np.clip((np.linspace(0, 1, HEIGHT) - 0.05) * 3, 0, 1)[:, None] * WASH
    canvas = canvas * (1 + 0.025 * blotches)[..., None]

    paint(canvas, "sky.svg", SKY_TOP)
    paint(canvas, "town.svg", TOWN_TOP)

    # paper grain over everything, also faded out at the top
    fade = np.clip(np.linspace(0, 1, HEIGHT) * 6, 0, 1)[:, None]
    canvas = canvas * (1 + 0.035 * fade * GRAIN)[..., None]
    out = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGB")
    target = HERE.parent / "static" / "town.webp"
    out.save(target, quality=80, method=6)
    print(target, out.size, target.stat().st_size // 1024, "KB")


main()
