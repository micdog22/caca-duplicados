"""Utilidades compartilhadas pelos testes: pastas temporárias com arquivos controlados."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.old_cwd)

    def make(self, rel: str, content: bytes, mtime: float = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def snapshot(self):
        return sorted(
            (p.relative_to(self.root).as_posix(), p.read_bytes()) for p in self.root.rglob("*") if p.is_file()
        )
