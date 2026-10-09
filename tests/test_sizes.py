import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from caca_duplicados.sizes import format_size, parse_size  # noqa: E402


class ParseSizeTests(unittest.TestCase):
    def test_units(self):
        cases = {
            "0": 0,
            "1024": 1024,
            "100B": 100,
            "1K": 1024,
            "1k": 1024,
            "1KB": 1024,
            "1kb": 1024,
            "1 KB": 1024,
            "1KiB": 1024,
            "1,5M": 1572864,
            "1.5MB": 1572864,
            "1,5 mb": 1572864,
            "2G": 2 * 1024 ** 3,
            "2gb": 2 * 1024 ** 3,
            "1T": 1024 ** 4,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_size(text), expected)

    def test_invalid(self):
        for text in ("", "abc", "M", "1X", "-1M", "1,5,5M", "1 M B", "um mega"):
            with self.subTest(text=text), self.assertRaises(ValueError) as ctx:
                parse_size(text)
            self.assertIn("tamanho inválido", str(ctx.exception))


class FormatSizeTests(unittest.TestCase):
    def test_portuguese_format(self):
        cases = {
            0: "0 bytes",
            1: "1 byte",
            1000: "1.000 bytes",
            1024: "1 KB",
            1536: "1,5 KB",
            1572864: "1,5 MB",
            1024 ** 3: "1 GB",
            int(1.25 * 1024 ** 3): "1,2 GB",
            1500 * 1024 ** 4: "1.500 TB",
        }
        for size, expected in cases.items():
            with self.subTest(size=size):
                self.assertEqual(format_size(size), expected)


if __name__ == "__main__":
    unittest.main()
