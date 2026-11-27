"""Generate the favicon set from the existing logo (frontend/public/logo.svg). Needs Pillow (dev only):  python backend/tools/make_favicons.py

The brand mark is NOT redrawn: the logo's traced polygon is read, lightly simplified (Ramer-Douglas-Peucker, 0.8 px on a 914x972 canvas) so the SVG favicon is a few KB
instead of 39 KB, and rendered black on a white rounded tile (PNG/ICO, which need an opaque/neutral background) or as a transparent SVG that switches to white in dark mode.
Outputs (frontend/public): favicon.svg, favicon.ico (16/32/48), favicon-16x16.png, favicon-32x32.png, apple-touch-icon.png (180), android-chrome-192x192.png,
android-chrome-512x512.png, maskable-512x512.png, site.webmanifest."""
import json
import pathlib
import re
import sys

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "public"
SRC = ROOT / "logo.svg"
INK, TILE = (10, 10, 10, 255), (255, 255, 255, 255)


def load_polygon() -> list[tuple[float, float]]:
    d = re.search(r' d="([^"]+)"', SRC.read_text(encoding="utf-8")).group(1)
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", d)]
    return list(zip(nums[0::2], nums[1::2]))


def rdp(pts, eps):
    """Iterative Ramer-Douglas-Peucker for a closed ring (split at the two farthest points)."""
    def dist(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / (dx * dx + dy * dy) ** 0.5
    def line(seq):
        keep = [False] * len(seq)
        keep[0] = keep[-1] = True
        stack = [(0, len(seq) - 1)]
        while stack:
            i, j = stack.pop()
            best, k = 0.0, None
            for m in range(i + 1, j):
                dm = dist(seq[m], seq[i], seq[j])
                if dm > best:
                    best, k = dm, m
            if k is not None and best > eps:
                keep[k] = True
                stack += [(i, k), (k, j)]
        return [p for p, kp in zip(seq, keep) if kp]
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    a, b = line(pts[:far + 1]), line(pts[far:] + [pts[0]])
    return a[:-1] + b[:-1]


def render(poly, size, *, pad, tile, radius=0.0, ss=4):
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    if tile:
        dr.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * radius), fill=TILE)
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    inner = big * (1 - 2 * pad)
    s = inner / max(w, h)
    ox, oy = (big - w * s) / 2 - min(xs) * s, (big - h * s) / 2 - min(ys) * s
    dr.polygon([(x * s + ox, y * s + oy) for x, y in poly], fill=INK)
    return img.resize((size, size), Image.LANCZOS)


def svg(poly) -> str:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    side = max(w, h) * 1.16
    ox, oy = (side - w) / 2 - min(xs), (side - h) / 2 - min(ys)
    d = "M" + " ".join(f"{x + ox:.0f} {y + oy:.0f}" for x, y in poly) + "Z"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side:.0f} {side:.0f}"><title>SYNAXYS</title>'
            '<style>path{fill:#0a0a0a}@media (prefers-color-scheme:dark){path{fill:#fff}}</style>'
            f'<path d="{d}"/></svg>\n')


def main() -> int:
    poly = rdp(load_polygon(), 0.8)
    (ROOT / "favicon.svg").write_text(svg(poly), encoding="utf-8")
    for name, size, kw in [("favicon-16x16.png", 16, dict(pad=0.08, tile=True, radius=0.2)), ("favicon-32x32.png", 32, dict(pad=0.1, tile=True, radius=0.2)),
                           ("apple-touch-icon.png", 180, dict(pad=0.16, tile=True)), ("android-chrome-192x192.png", 192, dict(pad=0.16, tile=True, radius=0.2)),
                           ("android-chrome-512x512.png", 512, dict(pad=0.16, tile=True, radius=0.2)), ("maskable-512x512.png", 512, dict(pad=0.28, tile=True))]:
        render(poly, size, **kw).save(ROOT / name, optimize=True)
    render(poly, 256, pad=0.1, tile=True, radius=0.2).save(ROOT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    (ROOT / "site.webmanifest").write_text(json.dumps({
        "name": "SYNAXYS", "short_name": "SYNAXYS", "description": "Smarter Reviews. Safer Code.", "start_url": "/app/dashboard", "display": "browser",
        "background_color": "#ffffff", "theme_color": "#0a0a0a",
        "icons": [{"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/maskable-512x512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}, indent=2) + "\n")
    print(f"points {len(load_polygon())} -> {len(poly)}; favicon.svg {(ROOT / 'favicon.svg').stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
