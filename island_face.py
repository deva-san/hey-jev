"""Her face in the island, as Nixi (heynixi.com) has one: two glowing eyes that blink, look around, wear glasses
while she reads the screen, headphones while music plays, turn to hearts when you say thanks, and nod off when
nothing's happened for a while. Drawn with numpy as signed distances, a few hundred pixels round each eye, so a
frame costs well under a millisecond; between blinks nothing is drawn at all.

The glass capsule (27 October 2026) has the same eyes, glowing in the colour of what she's doing (halo).

The shapes and glyphs the island's plugins use (a battery, play and pause, a progress ring, a tick) are here too.
"""
import math
import random
import time

import numpy as np

# --------------------------------------------------------------------------- shapes, as signed distances in px


def rbox(px, py, cx, cy, hw, hh, r):
    """A rounded rectangle centred on cx, cy: less than 0 inside."""
    r = max(0.0, min(r, hw, hh))
    qx, qy = np.abs(px - cx) - (hw - r), np.abs(py - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0)) + np.minimum(np.maximum(qx, qy), 0.0) - r


def circle(px, py, cx, cy, r):
    return np.hypot(px - cx, py - cy) - r


def segment(px, py, ax, ay, bx, by, width):
    """A line from a to b, width px wide, with round ends."""
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy or 1e-6
    h = np.clip(((px - ax) * dx + (py - ay) * dy) / length, 0.0, 1.0)
    return np.hypot(px - ax - h * dx, py - ay - h * dy) - width / 2


def arc(px, py, cx, cy, r, width, up=True):
    """The top (or bottom) half of a ring, with round ends: "^" eyes, a headphones' band."""
    dy = (py - cy) if up else (cy - py)
    ring = np.abs(np.hypot(px - cx, py - cy) - r) - width / 2
    ends = np.minimum(np.hypot(px - (cx - r), py - cy), np.hypot(px - (cx + r), py - cy)) - width / 2
    return np.where(dy <= 0, ring, ends)


def heart(px, py, cx, cy, size):
    """A heart about size px tall, point down (Inigo Quilez's heart)."""
    x = np.abs(px - cx) / size
    y = (cy + size * 0.52 - py) / size  # its point at the bottom
    d1 = np.hypot(x - 0.25, y - 0.75) - math.sqrt(2) / 4
    m = 0.5 * np.maximum(x + y, 0.0)
    d2 = np.sqrt(np.minimum((x - 0.0) ** 2 + (y - 1.0) ** 2, (x - m) ** 2 + (y - m) ** 2)) * np.sign(x - y)
    return np.where(x + y > 1.0, d1, d2) * size


def polygon(px, py, points):
    """A convex shape through points, either way round: the furthest of its edges' lines, near enough a
    distance for a pixel's smooth edge."""
    n = len(points)
    area = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))
    if area < 0:  # anticlockwise on screen: the same edges the other way
        points = points[::-1]
    d = None
    for i in range(n):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey) or 1e-6
        nx, ny = ey / length, -ex / length  # outwards, for points going round clockwise with y down
        side = (px - ax) * nx + (py - ay) * ny
        d = side if d is None else np.maximum(d, side)
    return d


# --------------------------------------------------------------------------- drawing into the island's pixels
class Canvas:
    """The island's colours, (h, w, 3) floats 0 to 1, drawn into a region at a time. ox, oy: where col's first
    pixel is in the coordinates things are drawn at, when col is only a part of the picture (whole pixels).
    op: for the glass capsule (27 October 2026), how opaque each pixel is, (h, w) 0 to 1, with col premultiplied by
    it: what's drawn goes over both, so words on the see-through glass come out solid."""

    def __init__(self, col, ox=0, oy=0, op=None):
        self.col = col
        self.h, self.w = col.shape[:2]
        self.ox, self.oy = int(ox), int(oy)
        self.op = op

    def _over(self, sl, m):
        """What's drawn with cover m (h, w, 1) makes those pixels that much more opaque (glass only)."""
        if self.op is not None:
            o = self.op[sl]
            o *= 1 - m[..., 0]
            o += m[..., 0]

    def region(self, x0, y0, x1, y1):
        """(slices of col, the pixels' x and y where they're drawn) for a box, or None if it's off col."""
        X0, Y0 = max(0, int(math.floor(x0 - self.ox))), max(0, int(math.floor(y0 - self.oy)))
        X1, Y1 = min(self.w, int(math.ceil(x1 - self.ox))), min(self.h, int(math.ceil(y1 - self.oy)))
        if X1 <= X0 or Y1 <= Y0:
            return None
        xs = np.arange(X0, X1, dtype=np.float32) + (0.5 + self.ox)
        ys = np.arange(Y0, Y1, dtype=np.float32)[:, None] + (0.5 + self.oy)
        return (slice(Y0, Y1), slice(X0, X1)), xs, ys

    def _part(self, pic, sl, X0, Y0):
        """The part of a picture placed at X0, Y0 that lands on the slices sl of col."""
        py, px = sl[0].start + self.oy - Y0, sl[1].start + self.ox - X0
        return pic[py:py + sl[0].stop - sl[0].start, px:px + sl[1].stop - sl[1].start]

    def shape(self, sd, bounds, colour, a=1.0, glow=0.0, spread=4.0, halo=None):
        """Fill sd(xs, ys) < 0 with colour; glow: light added round it, fading over spread px, in halo's colour if
        one's given (the capsule's eyes glow in the colour of what she's doing), else colour's."""
        r = self.region(*bounds)
        if r is None or a <= 0.003:
            return
        sl, xs, ys = r
        d = sd(xs, ys)
        dst = self.col[sl]
        colour = np.asarray(colour, np.float32)
        if glow > 0:
            g = np.exp(-np.maximum(d, 0.0) / spread) * (glow * a)
            dst += (colour if halo is None else np.asarray(halo, np.float32)) * g[..., None]
        cover = (np.clip(0.5 - d, 0.0, 1.0) * a)[..., None]
        dst *= 1 - cover
        dst += colour * cover
        self._over(sl, cover)

    def image(self, rgba, x, y, a=1.0):
        """A picture with its own alpha, premultiplied (island_art), at x, y."""
        h, w = rgba.shape[:2]
        X0, Y0 = int(round(x)), int(round(y))  # whole pixels, so the picture and its place are the same size
        r = self.region(X0, Y0, X0 + w, Y0 + h)
        if r is None or a <= 0.003:
            return
        sl = r[0]
        part = self._part(rgba, sl, X0, Y0)
        dst = self.col[sl]
        alpha = part[..., 3:4] * a
        dst *= 1 - alpha
        dst += part[..., :3] * a
        self._over(sl, alpha)

    def text(self, cover, x, y, colour, a=1.0):
        """Words (bubble.Text.render), in colour."""
        h, w = cover.shape
        X0, Y0 = int(round(x)), int(round(y))
        r = self.region(X0, Y0, X0 + w, Y0 + h)
        if r is None or a <= 0.003:
            return
        sl = r[0]
        m = (self._part(cover, sl, X0, Y0) * a)[..., None]
        dst = self.col[sl]
        dst *= 1 - m
        dst += np.asarray(colour, np.float32) * m
        self._over(sl, m)


# --------------------------------------------------------------------------- the eyes
WHITE = (0.97, 0.97, 0.98)
PINK = (1.0, 0.33, 0.6)
GOLD = (1.0, 0.84, 0.38)
RED = (1.0, 0.27, 0.23)
# the expressions, for Settings and for siri's "Mood": what each one is for
MOODS = {
    "open": "listening, and looking about when nothing's going on",
    "happy": "^ ^ when something's done, or you say hello",
    "love": "hearts when you say thanks",
    "surprised": "wide open when a notification comes in",
    "focus": "narrowed while she does something",
    "think": "looking up while she thinks",
    "glasses": "reading glasses while she looks at the screen",
    "headphones": "headphones while music plays",
    "sleepy": "half closed after a few quiet minutes",
    "sad": "drooping when something went wrong or the battery's low",
    "side": "a side look when it wasn't for her",
    "x": "crossed out for an error",
}
REACT_FOR = {"love": 2.6, "happy": 1.8, "surprised": 1.0, "sad": 2.2}  # seconds a reaction lasts


class Eyes:
    """Where the eyes are looking and how open they are, frame by frame: blinks every few seconds, glances about
    when there's nothing to do, and reactions (react) for a moment. update says when it next needs a frame."""

    def __init__(self, now=None):
        now = time.time() if now is None else now  # not 0: she'd start out asleep, five minutes "quiet" since then
        self.next_blink, self.blink_at, self.double = now + 2.0, None, False
        self.look = [0.0, 0.0]  # where it looks, -1 to 1 across and down, sprung to target
        self.look_v = [0.0, 0.0]
        self.target, self.next_look, self.hold_until = [0.0, 0.0], now + 4.0, 0.0
        self.mood, self.mood_until = None, 0.0
        self.last_active = now

    def react(self, mood, now):
        if mood in MOODS:
            self.mood, self.mood_until = mood, now + REACT_FOR.get(mood, 1.6)
            self.last_active = now

    def wake(self, now):
        self.last_active = now

    def update(self, now, dt, kind, wander=True, look_at=None):
        """(the expression to draw, how open 0 to 1, look x, look y, whether it's moving). kind: the scene's own
        expression; a reaction goes over it for a moment. look_at: where to look instead, -1 to 1, as at the
        mouse."""
        if self.mood and now >= self.mood_until:
            self.mood = None
        expr = self.mood or kind
        if expr == "open" and wander and now - self.last_active > 300:
            expr = "sleepy"  # five quiet minutes
        # blinks: closed for about a sixth of a second, sometimes twice
        open_ = 1.0
        blinking = expr in ("open", "surprised", "focus", "think", "glasses", "headphones", "sleepy", "side")
        if self.blink_at is None and now >= self.next_blink and blinking:
            self.blink_at = now
        if self.blink_at is not None:
            u = (now - self.blink_at) / 0.17
            if u >= 1:
                self.blink_at = None
                if not self.double and random.random() < 0.18:
                    self.double, self.next_blink = True, now + 0.12
                else:
                    self.double = False
                    gap = (5.0, 9.0) if expr == "sleepy" else (2.6, 6.2)
                    self.next_blink = now + random.uniform(*gap)
            else:
                open_ = 1 - 0.9 * math.sin(math.pi * u)
        # where it looks
        if look_at is not None and expr not in ("love", "happy", "x"):
            self.target = [float(look_at[0]), float(look_at[1])]
            self.last_active = now
        elif expr == "think":
            self.target = [0.55 if int(now / 1.4) % 2 else -0.55, -0.75]
        elif expr in ("focus",):
            self.target = [0.45 * math.sin(now * 1.7), 0.35]
        elif expr == "side":
            self.target = [0.95, 0.1]
        elif not wander or expr in ("love", "happy", "x", "sad"):
            self.target = [0.0, 0.0]
        elif now >= self.next_look:
            if self.target != [0.0, 0.0] or random.random() < 0.35:
                self.target, self.next_look = [0.0, 0.0], now + random.uniform(2.5, 6.0)
            else:
                self.target = random.choice([[-0.9, 0.0], [0.9, 0.0], [-0.6, -0.55], [0.6, -0.55], [0.0, 0.5],
                                             [-0.7, 0.35], [0.7, 0.35]])
                self.next_look = now + random.uniform(0.8, 1.9)
        moving = self.blink_at is not None
        for i in (0, 1):  # a quick, slightly springy glance
            k, c = 260.0, 26.0
            steps = max(1, math.ceil(dt / 0.004))
            h = dt / steps
            for _ in range(steps):
                self.look_v[i] += (-k * (self.look[i] - self.target[i]) - c * self.look_v[i]) * h
                self.look[i] += self.look_v[i] * h
            moving = moving or abs(self.look[i] - self.target[i]) > 0.004 or abs(self.look_v[i]) > 0.02
        return expr, open_, self.look[0], self.look[1], moving

    def wait(self, now):
        """Seconds till the next blink or glance, when nothing else moves."""
        return max(0.016, min(self.next_blink, self.next_look) - now)


def draw_eyes(cv, cx, cy, size, expr, open_=1.0, look=(0.0, 0.0), level=0.0, t=0.0, colour=WHITE, glow=True,
              a=1.0, halo=None):
    """Two eyes centred on cx, cy, each size px tall when open. level: a voice, 0 to 1, that makes them bounce.
    halo: the colour of their glow when it isn't their own (the glass capsule's, tinted by what's going on); the
    hearts keep their pink."""
    if a <= 0.003:
        return
    gx = glow * 0.5 if glow else 0.0
    spread = size * 0.2
    ew = size * 0.6
    gap = size * 2.0  # between their centres
    bounce = 1 + 0.12 * level
    lx, ly = look[0] * size * 0.36, look[1] * size * 0.26 - level * size * 0.08
    pad = size * 1.4

    def eye_box(ex, ey, w, h):
        return (ex - w - pad * 0.5, ey - h - pad * 0.5, ex + w + pad * 0.5, ey + h + pad * 0.5)

    for side in (-1, 1):
        ex, ey = cx + side * gap / 2 + lx, cy + ly
        if expr == "happy":
            r, w = size * 0.4, size * 0.22
            cv.shape(lambda xs, ys: arc(xs, ys, ex, ey + size * 0.16, r, w), eye_box(ex, ey, r, r), colour, a,
                     gx, spread, halo)
        elif expr == "love":
            s = size * 1.15 * (1 + 0.07 * math.sin(t * 7.5))
            cv.shape(lambda xs, ys: heart(xs, ys, ex, ey, s), eye_box(ex, ey, s * 0.7, s * 0.7), PINK, a,
                     0.55 if glow else 0.0, spread * 1.3)
        elif expr == "x":
            r, w = size * 0.34, size * 0.17
            cv.shape(lambda xs, ys: np.minimum(segment(xs, ys, ex - r, ey - r, ex + r, ey + r, w),
                                               segment(xs, ys, ex - r, ey + r, ex + r, ey - r, w)),
                     eye_box(ex, ey, r, r), RED, a, gx, spread)
        else:
            w = ew * (1.12 if expr == "surprised" else 0.86 if expr == "glasses" else 1.0)
            h = size * (1.18 if expr == "surprised" else 0.84 if expr == "glasses" else 1.0) * bounce
            if expr == "focus":
                h *= 0.58
            elif expr == "sleepy":
                h *= 0.3
            elif expr == "side":
                h *= 0.62
            h = max(size * 0.1, h * open_)
            yo = (size - h) * (0.32 if expr in ("sleepy", "focus", "side") else 0.0)  # lids come down, not up
            hw, hh = w / 2, h / 2
            if expr == "sad":  # the inner corners up: a worried look
                def sd(xs, ys, ex=ex, ey=ey + yo, hw=hw, hh=hh, side=side):
                    body = rbox(xs, ys, ex, ey, hw, hh, hw)
                    nx, ny = side * 0.55, -1.0  # cut lower on the outside, so the outer corners droop
                    norm = math.hypot(nx, ny)
                    lid = ((xs - ex) * nx + (ys - (ey - hh * 0.5)) * ny) / norm
                    return np.maximum(body, lid)
            else:
                def sd(xs, ys, ex=ex, ey=ey + yo, hw=hw, hh=hh):
                    return rbox(xs, ys, ex, ey, hw, hh, min(hw, hh))
            cv.shape(sd, eye_box(ex, ey + yo, hw, hh), colour, a, gx, spread, halo)
            if expr == "glasses":  # round frames over the eyes, and the bridge
                r, lw = size * 0.62, max(1.2, size * 0.09)
                cv.shape(lambda xs, ys: np.abs(circle(xs, ys, ex, ey, r)) - lw / 2, eye_box(ex, ey, r + lw, r + lw),
                         colour, a, gx * 0.6, spread, halo)
    if expr == "glasses":
        r, lw = size * 0.62, max(1.2, size * 0.09)
        ax, bx = cx - gap / 2 + lx + r, cx + gap / 2 + lx - r
        by = cy + ly - size * 0.12
        cv.shape(lambda xs, ys: segment(xs, ys, ax, by, bx, by, lw), (ax - 2, by - 3, bx + 2, by + 3), colour, a)
    elif expr == "headphones":  # a band over the top and a cup each side
        band_r, lw = gap / 2 + size * 0.5, max(1.4, size * 0.13)
        hx, hy = cx + lx * 0.3, cy + ly * 0.3 + size * 0.3  # worn low enough for the band to fit in the pill
        g = lw + 3.5 * spread  # room for the glow to fade out
        cv.shape(lambda xs, ys: arc(xs, ys, hx, hy, band_r, lw),
                 (hx - band_r - g, hy - band_r - g, hx + band_r + g, hy + g), colour, a * 0.9, gx * 0.5, spread,
                 halo)
        g = 1 + 3.5 * spread
        for side in (-1, 1):
            px = hx + side * band_r
            cv.shape(lambda xs, ys, px=px: rbox(xs, ys, px, hy + size * 0.05, size * 0.17, size * 0.36, size * 0.12),
                     (px - size * 0.17 - g, hy - size * 0.31 - g, px + size * 0.17 + g, hy + size * 0.41 + g), colour,
                     a, gx * 0.6, spread, halo)
    if expr in ("love", "happy") and glow:
        sparkles(cv, cx, cy, size, t, a)


def sparkles(cv, cx, cy, size, t, a=1.0):
    """Little stars that twinkle round the eyes when she's pleased."""
    for i, (ox, oy) in enumerate(((-1.85, -0.8), (1.9, -0.65), (1.55, 0.75), (-1.6, 0.7))):
        phase = (t * 1.6 + i * 0.37) % 1.0
        k = math.sin(math.pi * phase)
        if k < 0.05:
            continue
        sx, sy, r = cx + ox * size, cy + oy * size, size * 0.22 * k
        w = max(0.8, size * 0.055)
        g = 2 + 3.5 * size * 0.12  # room for the glow to fade out, so no square shows round it
        cv.shape(lambda xs, ys, sx=sx, sy=sy, r=r, w=w: np.minimum(segment(xs, ys, sx - r, sy, sx + r, sy, w),
                                                                   segment(xs, ys, sx, sy - r, sx, sy + r, w)),
                 (sx - r - g, sy - r - g, sx + r + g, sy + r + g), GOLD, a * k, 0.5, size * 0.12)


# --------------------------------------------------------------------------- the plugins' glyphs
def dots_row(cv, x, y, n, step, r, colour, level, t, mode, a=1.0):
    """A row of n dots from x, centred on y: they swell with level ("voice"), or a light runs along them
    ("busy")."""
    for i in range(n):
        if mode == "voice":
            wob = 0.5 + 0.5 * math.sin(t * 9.0 + i * 1.1)
            k = 0.55 + 0.45 * min(1.0, level * (0.6 + 0.8 * wob))
            rr, aa = r * (0.75 + 0.55 * k), a * (0.45 + 0.55 * k)
        else:
            k = max(0.0, math.cos((t * 1.6 - i / n) * math.tau)) ** 3
            rr, aa = r * (0.85 + 0.3 * k), a * (0.35 + 0.65 * k)
        px = x + i * step
        g = rr + 2 + 3.2 * r  # the glow fades out inside it
        cv.shape(lambda xs, ys, px=px, rr=rr: circle(xs, ys, px, y, rr), (px - g, y - g, px + g, y + g), colour,
                 aa, 0.25, r)


def meter(cv, x, y, h, colour, level, t, a=1.0, bars=3):
    """Nixi's three bars, left of the words, that move with your voice."""
    w = max(2.0, h * 0.2)
    for i in range(bars):
        wob = 0.5 + 0.5 * math.sin(t * 8.0 + i * 1.7)
        bh = h * (0.35 + 0.65 * min(1.0, 0.25 + level * (0.5 + wob)))
        bx = x + i * w * 1.9
        cv.shape(lambda xs, ys, bx=bx, bh=bh: rbox(xs, ys, bx, y, w / 2, bh / 2, w / 2),
                 (bx - w, y - h / 2 - 1, bx + w, y + h / 2 + 1), colour, a)


def battery(cv, x, y, h, percent, colour, fill, charging, a=1.0):
    """A battery on its side, h px tall, filled to percent, with a bolt while charging."""
    w = h * 1.9
    lw = max(1.0, h * 0.11)
    cx, cy = x + w / 2, y
    cv.shape(lambda xs, ys: np.abs(rbox(xs, ys, cx, cy, w / 2, h / 2, h * 0.28)) - lw / 2,
             (x - 2, y - h / 2 - 2, x + w + 2, y + h / 2 + 2), colour, a * 0.65)
    nub = x + w + lw * 1.3
    cv.shape(lambda xs, ys: rbox(xs, ys, nub, cy, lw * 0.8, h * 0.18, lw * 0.6), (nub - 3, cy - h / 2, nub + 3,
                                                                                  cy + h / 2), colour, a * 0.65)
    inner_w = (w - lw * 3.2) * max(0.06, min(1.0, percent / 100))
    fx = x + lw * 1.6
    cv.shape(lambda xs, ys: rbox(xs, ys, fx + inner_w / 2, cy, inner_w / 2, h / 2 - lw * 1.6, h * 0.14),
             (fx - 1, y - h / 2, fx + inner_w + 1, y + h / 2), fill, a)
    if charging:
        s = h * 0.46
        pts = [(cx + 0.15 * s, cy - s), (cx - 0.55 * s, cy + 0.12 * s), (cx - 0.05 * s, cy + 0.12 * s)]
        pts2 = [(cx - 0.15 * s, cy + s), (cx + 0.55 * s, cy - 0.12 * s), (cx + 0.05 * s, cy - 0.12 * s)]
        for p in (pts, pts2):
            cv.shape(lambda xs, ys, p=p: polygon(xs, ys, p), (cx - s, cy - s - 1, cx + s, cy + s + 1),
                     (1.0, 1.0, 1.0), a)


def ring(cv, cx, cy, r, width, left, colour, back, a=1.0):
    """A ring running down clockwise from the top, like a timer: left, the part still to go, 0 to 1."""
    def sd(xs, ys):
        return np.abs(circle(xs, ys, cx, cy, r)) - width / 2
    box = (cx - r - width, cy - r - width, cx + r + width, cy + r + width)
    cv.shape(sd, box, back, a)

    def done(xs, ys):
        turn = (np.arctan2(xs - cx, -(ys - cy)) % math.tau) / math.tau
        return np.where(turn <= left, sd(xs, ys), 9.0)
    cv.shape(done, box, colour, a)


def play_glyph(cv, cx, cy, s, playing, colour, a=1.0):
    """Pause bars while it plays, else a play triangle, s px tall."""
    if playing:
        for side in (-1, 1):
            bx = cx + side * s * 0.22
            cv.shape(lambda xs, ys, bx=bx: rbox(xs, ys, bx, cy, s * 0.12, s * 0.42, s * 0.06),
                     (bx - s * 0.2, cy - s * 0.5, bx + s * 0.2, cy + s * 0.5), colour, a)
    else:
        pts = [(cx - s * 0.32, cy - s * 0.45), (cx + s * 0.45, cy), (cx - s * 0.32, cy + s * 0.45)]
        cv.shape(lambda xs, ys: polygon(xs, ys, pts) - s * 0.02, (cx - s * 0.5, cy - s * 0.55, cx + s * 0.6,
                                                                cy + s * 0.55), colour, a)


def skip_glyph(cv, cx, cy, s, forward, colour, a=1.0):
    """Next or previous: a triangle and a bar."""
    d = 1 if forward else -1
    tip = cx + d * s * 0.28
    back = cx - d * s * 0.32
    pts = [(back, cy - s * 0.4), (tip, cy), (back, cy + s * 0.4)] if forward else \
        [(back, cy + s * 0.4), (tip, cy), (back, cy - s * 0.4)]
    cv.shape(lambda xs, ys: polygon(xs, ys, pts) - s * 0.02, (cx - s * 0.6, cy - s * 0.5, cx + s * 0.6,
                                                            cy + s * 0.5), colour, a)
    bar = cx + d * s * 0.38
    cv.shape(lambda xs, ys: rbox(xs, ys, bar, cy, s * 0.06, s * 0.4, s * 0.05),
             (bar - s * 0.12, cy - s * 0.5, bar + s * 0.12, cy + s * 0.5), colour, a)


def tick_glyph(cv, cx, cy, s, colour, a=1.0):
    """A tick about s px across, for something done."""
    w = max(1.2, s * 0.16)
    (ax, ay), (bx, by), (ex, ey) = (cx - s * 0.36, cy + s * 0.02), (cx - s * 0.1, cy + s * 0.28), \
        (cx + s * 0.38, cy - s * 0.26)
    cv.shape(lambda xs, ys: np.minimum(segment(xs, ys, ax, ay, bx, by, w), segment(xs, ys, bx, by, ex, ey, w)),
             (cx - s * 0.5 - w, cy - s * 0.4 - w, cx + s * 0.5 + w, cy + s * 0.4 + w), colour, a)


def close_glyph(cv, cx, cy, s, colour, a=1.0):
    r, w = s * 0.32, max(1.0, s * 0.12)
    cv.shape(lambda xs, ys: np.minimum(segment(xs, ys, cx - r, cy - r, cx + r, cy + r, w),
                                       segment(xs, ys, cx - r, cy + r, cx + r, cy - r, w)),
             (cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), colour, a)


def equalizer(cv, x, cy, h, colour, level, t, a=1.0, bars=4):
    """Bars that dance while music plays, by what the speakers are playing when that's known."""
    w = max(1.6, h * 0.16)
    for i in range(bars):
        wob = 0.5 + 0.5 * math.sin(t * (6.5 + i * 1.3) + i * 2.1)
        bh = h * (0.25 + 0.75 * min(1.0, (0.35 + 0.65 * wob) * (0.3 + 0.9 * level)))
        bx = x + i * w * 2.0
        cv.shape(lambda xs, ys, bx=bx, bh=bh: rbox(xs, ys, bx, cy + (h - bh) / 2, w / 2, bh / 2, w / 2),
                 (bx - w, cy - h / 2 - 1, bx + w, cy + h / 2 + 1), colour, a)
