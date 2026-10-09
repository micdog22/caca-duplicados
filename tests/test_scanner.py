import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from caca_duplicados.scanner import CHUNK, collect_files, find_duplicates, normalize_extensions  # noqa: E402
from helpers import TempDirTestCase  # noqa: E402


def scan(*roots, **options):
    result = collect_files([str(r) for r in roots], **options)
    groups = find_duplicates(result)
    return result, groups


def group_paths(groups):
    return [sorted(f.rel.as_posix() for f in g.files) for g in groups]


class DetectionTests(TempDirTestCase):
    def test_same_content_different_names(self):
        self.make("a/foto.jpg", b"conteudo igual" * 100)
        self.make("b/IMG_0001 (1).jpg", b"conteudo igual" * 100)
        self.make("c/outro.jpg", b"conteudo diferente" * 100)
        _, groups = scan(self.root)
        self.assertEqual(group_paths(groups), [["a/foto.jpg", "b/IMG_0001 (1).jpg"]])
        self.assertEqual(groups[0].wasted, 1400)

    def test_same_size_different_content(self):
        self.make("um.bin", b"a" * 5000)
        self.make("dois.bin", b"b" * 5000)
        self.assertEqual(scan(self.root)[1], [])

    def test_same_prefix_different_end(self):
        prefix = os.urandom(CHUNK)
        self.make("um.bin", prefix + b"x" * CHUNK * 2)
        self.make("dois.bin", prefix + b"x" * (CHUNK * 2 - 1) + b"y")
        self.assertEqual(scan(self.root)[1], [])

    def test_same_start_and_end_different_middle(self):
        start, end = os.urandom(CHUNK), os.urandom(CHUNK)
        self.make("um.bin", start + b"meio-1" + b"." * CHUNK + end)
        self.make("dois.bin", start + b"meio-2" + b"." * CHUNK + end)
        self.assertEqual(scan(self.root)[1], [])

    def test_large_identical_files(self):
        data = os.urandom(3 * CHUNK + 123)
        for name in ("a.iso", "b.iso", "c/c.iso"):
            self.make(name, data)
        _, groups = scan(self.root)
        self.assertEqual(group_paths(groups), [["a.iso", "b.iso", "c/c.iso"]])
        self.assertEqual(groups[0].wasted, 2 * len(data))

    def test_groups_sorted_by_wasted_space(self):
        self.make("p1.txt", b"p" * 10)
        self.make("p2.txt", b"p" * 10)
        self.make("g1.txt", b"g" * 1000)
        self.make("g2.txt", b"g" * 1000)
        _, groups = scan(self.root)
        self.assertEqual([g.size for g in groups], [1000, 10])

    def test_empty_files_are_optional(self):
        self.make("vazio1", b"")
        self.make("vazio2", b"")
        result, groups = scan(self.root)
        self.assertEqual(groups, [])
        self.assertEqual(result.skipped_empty, 2)
        _, groups = scan(self.root, include_empty=True)
        self.assertEqual(group_paths(groups), [["vazio1", "vazio2"]])

    def test_symlinks_are_skipped(self):
        target = self.make("original.txt", b"dados" * 10)
        try:
            os.symlink(target, self.root / "atalho.txt")
            os.symlink(self.root, self.root / "pasta-atalho")
        except (OSError, NotImplementedError):
            self.skipTest("links simbólicos indisponíveis")
        result, groups = scan(self.root)
        self.assertEqual(groups, [])
        self.assertEqual(result.skipped_links, 2)

    def test_hardlinks_are_not_reported(self):
        original = self.make("original.txt", b"dados" * 10)
        try:
            os.link(original, self.root / "hardlink.txt")
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks indisponíveis")
        result, groups = scan(self.root)
        self.assertEqual(groups, [])
        self.assertEqual(result.same_inode, 1)

    def test_overlapping_folders_do_not_duplicate_files(self):
        self.make("Fotos/2024/praia.jpg", b"foto" * 50)
        self.make("Fotos/outra.jpg", b"outra" * 50)
        result, groups = scan(self.root / "Fotos" / "2024", self.root / "Fotos")
        self.assertEqual(groups, [])
        self.assertEqual(len(result.files), 2)
        result, _ = scan(self.root / "Fotos", self.root / "Fotos" / "2024")
        self.assertEqual(len(result.files), 2)


class FilterTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        contents = {"fotos": b"f" * 2048, "docs": b"pequeno", "node_modules": b"n" * 2048}
        for rel in ("fotos/a.JPG", "fotos/b.jpg", "docs/a.pdf", "docs/b.pdf", "node_modules/x.js", "node_modules/y.js"):
            self.make(rel, contents[rel.split("/")[0]])

    def test_min_size(self):
        _, groups = scan(self.root, min_size=1024)
        self.assertEqual(sorted(group_paths(groups)), [["fotos/a.JPG", "fotos/b.jpg"], ["node_modules/x.js", "node_modules/y.js"]])

    def test_extensions(self):
        self.assertEqual(normalize_extensions(" .JPG, png ,,"), {"jpg", "png"})
        _, groups = scan(self.root, extensions=normalize_extensions("jpg"))
        self.assertEqual(group_paths(groups), [["fotos/a.JPG", "fotos/b.jpg"]])

    def test_ignore_patterns(self):
        _, groups = scan(self.root, ignore=["node_modules", "*.PDF"])
        self.assertEqual(group_paths(groups), [["fotos/a.JPG", "fotos/b.jpg"]])
        _, groups = scan(self.root, ignore=["fotos/*"])
        self.assertEqual(sorted(group_paths(groups)), [["docs/a.pdf", "docs/b.pdf"], ["node_modules/x.js", "node_modules/y.js"]])

    def test_excluded_folder(self):
        _, groups = scan(self.root, exclude=[self.root / "node_modules"])
        self.assertNotIn(["node_modules/x.js", "node_modules/y.js"], group_paths(groups))

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissões POSIX")
    def test_unreadable_file_is_reported(self):
        locked = self.make("fotos/c.jpg", b"f" * 2048)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        result, groups = scan(self.root / "fotos")
        self.assertEqual(group_paths(groups), [["a.JPG", "b.jpg"]])
        self.assertEqual([(p.name, reason) for p, reason in result.unreadable], [("c.jpg", "sem permissão de leitura")])


if __name__ == "__main__":
    unittest.main()
