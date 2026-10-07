"""Vision mode's eyes: a screenshot of the screen in front, made small enough to send to the answer model, and the
way back from a point in it to a point on the screen. Only taken when you ask her to look, see siri.see()."""
import base64
import struct
import zlib

import numpy as np

import winplatform as win

WIDTH = 1280  # the free model pointed inside the right button 6 times out of 6 at this size


def shrink(rgb, width=WIDTH):
    """rgb made width pixels wide, each new pixel the average of the ones it covers, so text stays readable."""
    h, w = rgb.shape[:2]
    if w <= width:
        return rgb
    xs = np.round(np.linspace(0, w, width + 1)).astype(int)
    ys = np.round(np.linspace(0, h, round(h * width / w) + 1)).astype(int)
    total = np.add.reduceat(np.add.reduceat(rgb.astype(np.uint32), xs[:-1], axis=1), ys[:-1], axis=0)
    return (total / np.outer(np.diff(ys), np.diff(xs))[..., None]).astype(np.uint8)


def png(rgb):
    """rgb as a PNG file, no image library needed. A 1280 x 800 screen of an app is about 150 KB."""
    h, w, _ = rgb.shape
    raw = np.zeros((h, w * 3 + 1), np.uint8)  # each row starts with its filter, 0: none, the smallest for screens
    raw[:, 1:] = np.ascontiguousarray(rgb).reshape(h, w * 3)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)) + chunk(b"IEND", b""))


class Shot:
    """A screenshot ready to send: url is the picture, w and h its size in pixels, rect where it is on the screen."""

    def __init__(self, rgb, rect):
        self.small = shrink(rgb)
        self.h, self.w = self.small.shape[:2]
        self.rect, self.scale = rect, (rect[2] - rect[0]) / self.w
        self.png = png(self.small)
        self.url = "data:image/png;base64," + base64.b64encode(self.png).decode()

    def same_as(self, other):
        """True if the screen looks the same as in another shot, as after a click that did nothing."""
        return self.small.shape == other.small.shape and \
            float(np.abs(self.small.astype(np.int16) - other.small).mean()) < 0.6

    def to_screen(self, x, y):
        """A point in the picture as a point on the screen, in real pixels. None if it's outside the picture."""
        if not (0 <= x <= self.w and 0 <= y <= self.h):
            return None
        return round(self.rect[0] + x * self.scale), round(self.rect[1] + y * self.scale)


def capture():
    """The screen in front now, as a Shot. Her popup is left out of it."""
    return Shot(*win.screenshot())
