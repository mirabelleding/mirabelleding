# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=12"]
# ///

import argparse
import base64
import io
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

WIDTH, HEIGHT = 2473, 703
CYCLE = 15.0
START = 0.55
CHAR_INTERVAL = 0.07
LINE_GAP = 0.50
RESET = 14.25
BLINK_INTERVAL = 0.40

ROOT = Path(__file__).resolve().parent.parent
SIGNATURES = ROOT / "signatures"


@dataclass(frozen=True)
class TextLine:
    text: str
    x: int
    y: int
    width: int
    height: int
    reveal_width: int
    cursor_y: int
    cursor_height: int
    cursor_color: str
    start: float = 0.0
    edges: tuple[int, ...] = ()

    @property
    def end(self) -> float:
        return self.start + len(self.text) * CHAR_INTERVAL


def lines() -> list[TextLine]:
    specs = [
        ("from mi77_lab import mirabelleding", 64, 35, 1025, 77, 1025, 46, 51, "#c4a6fe"),
        ("# some magic and inspirations", 53, 212, 900, 88, 881, 226, 69, "#a4a4a4"),
        ("mirabelleding", 2097, 539, 315, 65, 315, 549, 45, "#f1f6fc"),
        ("MI77-LAB", 2153, 606, 260, 61, 260, 615, 38, "#8f5d7c"),
    ]
    result = []
    start = START
    for spec in specs:
        line = TextLine(*spec, start=start)
        result.append(line)
        start = line.end + LINE_GAP
    if start >= RESET:
        raise ValueError("Animation is longer than the available cycle")
    return result


def erase_text(source: Image.Image, text_lines: list[TextLine]) -> Image.Image:
    base = source.copy()
    for line in text_lines:
        strip = source.crop((line.x, 350, line.x + line.width, 351))
        base.paste(strip.resize((line.width, line.height), Image.Resampling.NEAREST), (line.x, line.y))
    return base


def precise_edges(source: Image.Image, base: Image.Image, line: TextLine) -> tuple[int, ...]:
    box = (line.x, line.y, line.x + line.reveal_width, line.y + line.height)
    difference = ImageChops.difference(source.crop(box), base.crop(box)).convert("L")
    occupied = [bool(difference.crop((x, 0, x + 1, line.height)).getbbox()) for x in range(line.reveal_width)]
    runs = []
    start = None
    for x, ink in enumerate(occupied + [False]):
        if ink and start is None:
            start = x
        elif not ink and start is not None:
            runs.append((start, x - 1))
            start = None
    nonspace = [i for i, char in enumerate(line.text) if char != " "]
    if len(runs) != len(nonspace):
        return tuple(round(line.reveal_width * i / len(line.text)) for i in range(1, len(line.text) + 1))
    glyphs = dict(zip(nonspace, runs, strict=True))
    edges = []
    for i, char in enumerate(line.text):
        if char != " ":
            edge = glyphs[i][1] + 2
        else:
            next_char = next(j for j in nonspace if j > i)
            edge = glyphs[next_char][0] - 2
        edges.append(max(edges[-1] if edges else 0, min(edge, line.reveal_width)))
    edges[-1] = line.reveal_width
    return tuple(edges)


def png_data(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def animation(points: list[tuple[float, int]], attribute: str, duration: float = CYCLE) -> str:
    points = sorted(points)
    values = ";".join(str(value) for _, value in points)
    times = ";".join(f"{min(t / duration, 1):.6f}" for t, _ in points)
    return (
        f'<animate attributeName="{attribute}" values="{values}" '
        f'keyTimes="{times}" calcMode="discrete" dur="{duration}s" '
        'repeatCount="indefinite"/>'
    )


def typing_points(line: TextLine) -> list[tuple[float, int]]:
    points = [(0.0, 0), (line.start, 0)]
    points.extend(
        (line.start + i * CHAR_INTERVAL, line.edges[i - 1])
        for i in range(1, len(line.text) + 1)
    )
    points.extend([(RESET, line.reveal_width), (RESET + 0.015, 0), (CYCLE, 0)])
    return points


def caret_intervals(text_lines: list[TextLine], index: int) -> list[tuple[float, float]]:
    line = text_lines[index]
    if index == 0:
        return [(line.start, text_lines[1].start)]
    if index == 1:
        return [(line.start, text_lines[2].start), (text_lines[3].end + 0.2, RESET)]
    if index == 2:
        return [(line.start, text_lines[3].start)]
    return [(line.start, line.end + 0.2)]


def visibility_points(intervals: list[tuple[float, float]]) -> list[tuple[float, int]]:
    points = [(0.0, 0)]
    for start, end in intervals:
        points.extend([(start, 1), (end, 0)])
    points.append((CYCLE, 0))
    return points


def caret(line: TextLine, intervals: list[tuple[float, float]], index: int) -> str:
    positions = [(t, line.x + 1 + w) for t, w in typing_points(line)]
    positions[-3:] = [(RESET, line.x + 1 + line.reveal_width), (RESET + 0.015, line.x + 1), (CYCLE, line.x + 1)]
    visible = animation(visibility_points(intervals), "opacity")
    move = animation(positions, "x")
    blink = (
        f'<animate attributeName="opacity" values="1;0" keyTimes="0;0.5" '
        f'calcMode="discrete" dur="{2 * BLINK_INTERVAL}s" repeatCount="indefinite"/>'
    )
    return (
        f'<g class="caret" opacity="0">{visible}'
        f'<rect x="{line.x + 1}" y="{line.cursor_y}" width="8" '
        f'height="{line.cursor_height}" fill="{line.cursor_color}">'
        f'{move}{blink}</rect></g>'
    )


def render_svg(source: Image.Image, base: Image.Image, text_lines: list[TextLine]) -> str:
    defs = []
    layers = []
    overrides = []
    for i, line in enumerate(text_lines):
        defs.append(
            f'<clipPath id="typing-{i}"><rect x="{line.x}" y="{line.y}" '
            f'width="{line.reveal_width}" height="{line.height}">'
            f'{animation(typing_points(line), "width")}</rect></clipPath>'
        )
        layers.append(f'<use href="#source" clip-path="url(#typing-{i})"/>')
        overrides.append(f'#typing-{i} rect {{ width: {line.reveal_width}px !important; }}')
    carets = [caret(line, caret_intervals(text_lines, i), i) for i, line in enumerate(text_lines)]
    desc = "; ".join(line.text for line in text_lines)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        'role="img" aria-labelledby="banner-title banner-description">\n'
        '<title id="banner-title">MI77-LAB animated signature</title>\n'
        f'<desc id="banner-description">{escape(desc)}</desc>\n'
        '<style>@media (prefers-reduced-motion: reduce) {'
        + " ".join(overrides)
        + ' .caret { display: none; } }</style>\n'
        f'<defs><image id="source" width="{WIDTH}" height="{HEIGHT}" '
        f'href="data:image/png;base64,{png_data(source)}"/>\n'
        + "\n".join(defs)
        + '</defs>\n'
        f'<image width="{WIDTH}" height="{HEIGHT}" href="data:image/png;base64,{png_data(base)}"/>\n'
        + "\n".join(layers)
        + "\n".join(carets)
        + '\n</svg>\n'
    )


def frame_at(source: Image.Image, base: Image.Image, text_lines: list[TextLine], t: float) -> Image.Image:
    frame = base.copy()
    draw = ImageDraw.Draw(frame)
    if t >= RESET + 0.015:
        return frame
    active = []
    for i, line in enumerate(text_lines):
        count = max(0, min(len(line.text), int((t - line.start + 0.0001) / CHAR_INTERVAL)))
        pixels = line.edges[count - 1] if count else 0
        if pixels:
            area = (line.x, line.y, line.x + pixels, line.y + line.height)
            frame.paste(source.crop(area), (line.x, line.y))
        if any(start <= t < end for start, end in caret_intervals(text_lines, i)):
            active.append((line, pixels))
    if int((t + 0.0001) / BLINK_INTERVAL) % 2 == 0:
        for line, pixels in active:
            x = line.x + 1 + pixels
            draw.rectangle((x, line.cursor_y, x + 7, line.cursor_y + line.cursor_height - 1), fill=line.cursor_color)
    return frame


def render_gif(source: Image.Image, base: Image.Image, text_lines: list[TextLine], target: Path) -> None:
    moments = {0.0, RESET, RESET + 0.02}
    for line in text_lines:
        moments.add(line.start)
        moments.update(line.start + i * CHAR_INTERVAL for i in range(1, len(line.text) + 1))
    for i in range(1, int(CYCLE / BLINK_INTERVAL) + 1):
        moments.add(i * BLINK_INTERVAL)
    for i in range(len(text_lines)):
        for start, end in caret_intervals(text_lines, i):
            moments.update((start, end))
    times = sorted({round(t, 3) for t in moments if t < CYCLE})
    palette = source.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    frames = [frame_at(source, base, text_lines, t).quantize(palette=palette, dither=Image.Dither.NONE) for t in times]
    durations = [round((next_t - t) * 1000) for t, next_t in zip(times, times[1:] + [CYCLE])]
    target.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        target,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=SIGNATURES / "mi77_banner_lab.png",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=SIGNATURES / "mi77_banner_lab_animated.svg",
    )
    parser.add_argument(
        "--gif",
        type=Path,
        default=SIGNATURES / "mi77_banner_lab_animated.gif",
    )
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    with Image.open(args.source) as img:
        source = img.convert("RGB")
    if source.size != (WIDTH, HEIGHT):
        raise ValueError(f"Expected {WIDTH} x {HEIGHT} source, received {source.size}")

    text_lines = lines()
    base = erase_text(source, text_lines)
    text_lines = [replace(line, edges=precise_edges(source, base, line)) for line in text_lines]
    args.svg.parent.mkdir(parents=True, exist_ok=True)
    args.svg.write_text(render_svg(source, base, text_lines), encoding="utf-8")
    print(f"Wrote {args.svg}")

    if not args.no_gif:
        render_gif(source, base, text_lines, args.gif)
        print(f"Wrote {args.gif}")


if __name__ == "__main__":
    main()
