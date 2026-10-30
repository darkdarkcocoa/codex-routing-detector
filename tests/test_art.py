"""tools/key_green.py: green-screen keying of the mascot art (build-time tool; needs numpy and Pillow)."""
import contextlib
import importlib.util
import io
import pathlib
import unittest

try:
    import numpy as np
    from PIL import Image
except ImportError:  # the app itself needs neither
    np = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
HAIR = (205, 130, 115)
GREEN = (0, 255, 0)


def load_tool():
    spec = importlib.util.spec_from_file_location("key_green", ROOT / "tools" / "key_green.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def blend(fg, share):
    return tuple(round(f * share + g * (1 - share)) for f, g in zip(fg, GREEN))


@unittest.skipIf(np is None, "numpy and Pillow are build-time only")
class GreenKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = load_tool()

    def keyed(self, *pixels):
        img = Image.new("RGB", (len(pixels), 1))
        img.putdata(list(pixels))
        out = self.kg.key_rgba(img)
        return [out.getpixel((x, 0)) for x in range(out.width)]

    def test_pure_green_is_transparent_and_art_colours_stay_opaque(self):
        green, skin, hair, teal, white, gold = self.keyed(
            GREEN, (250, 222, 205), HAIR, (70, 170, 175), (255, 255, 255), (220, 170, 60))
        self.assertEqual(green, (0, 0, 0, 0))
        for px in (skin, hair, teal, white, gold):
            self.assertEqual(px[3], 255, px)
        self.assertEqual(skin[:3], (250, 222, 205))

    def test_hair_edges_keep_the_hair_colour(self):
        # regression: dividing by an alpha taken from the green surplus turned a half-hair edge pixel
        # magenta (255, 0, 255) and left an 80 % one opaque olive
        for share in (0.3, 0.5, 0.6, 0.8, 0.9):
            r, g, b, a = self.keyed(blend(HAIR, share))[0]
            self.assertLessEqual(g, max(r, b), share)
            self.assertLess(abs(r - HAIR[0]) + abs(g - HAIR[1]) + abs(b - HAIR[2]), 90, (share, r, g, b))
            self.assertGreater(a, 0, share)

    def test_dark_outline_mixed_with_green_loses_the_tint(self):
        # the hair's outer outline, dark ink blended into the green, typically about (28, 60, 14) in the raw
        r, g, b, a = self.keyed((28, 60, 14))[0]
        self.assertLess(a, 255)
        self.assertLessEqual(g, r)

    def test_background_noise_disappears_without_colour(self):
        self.assertEqual(self.keyed((6, 248, 4))[0], (0, 0, 0, 0))

    def test_key_crops_to_the_content(self):
        img = Image.new("RGB", (40, 30), GREEN)
        img.paste((200, 120, 110), (10, 5, 20, 25))
        self.assertEqual(self.kg.key(img).size, (10, 20))

    def test_shrink_keeps_the_longest_side_and_clears_stray_colour(self):
        img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
        img.paste((200, 120, 110, 255), (100, 50, 300, 150))
        small = self.kg.shrink(img, 100)
        self.assertEqual(small.size, (100, 50))
        a = np.asarray(small)
        self.assertFalse(((a[..., 3] < 3) & (a[..., :3].sum(axis=2) > 0)).any())
        self.assertIs(self.kg.shrink(img, 0), img)

    def test_crossfade_loop_keeps_the_body_and_blends_the_start(self):
        frames = [Image.new("RGBA", (2, 2), (i * 10, 0, 0, 255)) for i in range(10)]
        out = self.kg.crossfade_loop(frames, 2)
        self.assertEqual(len(out), 8)
        self.assertEqual([f.getpixel((0, 0)) for f in out[2:]], [f.getpixel((0, 0)) for f in frames[2:8]])
        first = out[0].getpixel((0, 0))[0]
        self.assertTrue(0 < first < 80)  # between frame 0 (0) and frame 8 (80)
        self.assertEqual(self.kg.crossfade_loop(frames, 0), frames)

    def test_unknown_or_incomplete_options_are_refused(self):
        # regression: a mistyped option (--fsp) was silently ignored and a trailing flag dropped
        for argv in (["frames", "v.mp4", "o.webp", "0", "10", "--fsp", "24"],
                     ["frames", "v.mp4", "o.webp", "0", "10", "--fps"],
                     ["image", "raw.png"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.kg.main(argv)


if __name__ == "__main__":
    unittest.main()
