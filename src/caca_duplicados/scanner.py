"""Busca de duplicados: tamanho -> hash parcial -> hash completo (BLAKE2b)."""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import os
import stat
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

CHUNK = 64 * 1024
READ_BLOCK = 1024 * 1024

Progress = Optional[Callable[[str, int, int], None]]


@dataclass
class FileInfo:
    path: Path  # como será exibido (pasta informada + caminho relativo)
    root: int  # índice da pasta informada na linha de comando
    rel: PurePath  # caminho relativo à pasta informada
    size: int
    mtime: float
    dev: int
    ino: int
    order: int  # ordem de descoberta: pastas na ordem informada, nomes em ordem alfabética


@dataclass
class DuplicateGroup:
    size: int
    digest: str
    files: List[FileInfo]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)


@dataclass
class ScanResult:
    files: List[FileInfo] = field(default_factory=list)
    groups: List[DuplicateGroup] = field(default_factory=list)
    unreadable: List[Tuple[Path, str]] = field(default_factory=list)
    skipped_links: int = 0
    skipped_empty: int = 0
    skipped_filtered: int = 0
    same_inode: int = 0


def describe_error(exc: OSError) -> str:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "sem permissão de leitura"
    if exc.errno == errno.ENOENT:
        return "o arquivo não existe mais"
    return exc.strerror or str(exc)


def normalize_extensions(raw: Optional[str]) -> Optional[set]:
    if not raw:
        return None
    exts = {e.strip().lstrip(".").lower() for e in raw.split(",") if e.strip().lstrip(".")}
    return exts or None


def _matches(rel: PurePath, patterns: Sequence[str]) -> bool:
    """Compara o padrão com o nome, com cada pasta do caminho e com o caminho inteiro."""
    if not patterns:
        return False
    candidates = [part.lower() for part in rel.parts] + [rel.as_posix().lower()]
    return any(fnmatch.fnmatchcase(c, p.lower()) for p in patterns for c in candidates)


def collect_files(
    roots: Sequence[str],
    min_size: int = 0,
    include_empty: bool = False,
    ignore: Sequence[str] = (),
    extensions: Optional[set] = None,
    exclude: Iterable[Path] = (),
    progress: Progress = None,
) -> ScanResult:
    """Lista os arquivos candidatos, sem seguir links simbólicos."""
    result = ScanResult()
    excluded = {Path(p).resolve() for p in exclude}
    seen_inodes: Dict[Tuple[int, int], FileInfo] = {}

    def consider(path: Path, root_index: int, rel: PurePath) -> None:
        try:
            st = os.lstat(path)
        except OSError as exc:
            result.unreadable.append((path, describe_error(exc)))
            return
        if stat.S_ISLNK(st.st_mode):
            result.skipped_links += 1
            return
        if not stat.S_ISREG(st.st_mode):
            return
        if st.st_size == 0 and not include_empty:
            result.skipped_empty += 1
            return
        suffix = rel.name.rsplit(".", 1)[-1].lower() if "." in rel.name else ""
        if st.st_size < min_size or (extensions and suffix not in extensions) or _matches(rel, ignore):
            result.skipped_filtered += 1
            return
        key = (st.st_dev, st.st_ino)
        if st.st_ino and key in seen_inodes:
            result.same_inode += 1  # mesmo arquivo (hardlink ou pasta repetida): não ocupa espaço extra
            return
        info = FileInfo(path, root_index, rel, st.st_size, st.st_mtime, st.st_dev, st.st_ino, len(result.files))
        seen_inodes[key] = info
        result.files.append(info)
        if progress:
            progress("arquivos", len(result.files), 0)

    def walk_error(exc: OSError) -> None:
        result.unreadable.append((Path(exc.filename), describe_error(exc)))

    walked: List[Path] = []
    for index, root in enumerate(roots):
        base = Path(root)
        resolved = base.resolve()
        if any(resolved == w or w in resolved.parents for w in walked):
            continue  # já coberta por uma pasta informada antes
        walked_before = set(walked)
        walked.append(resolved)
        if not base.is_dir():
            consider(base, index, PurePath(base.name))
            continue
        for dirpath, dirnames, filenames in os.walk(base, onerror=walk_error):
            current = Path(dirpath)
            rel_dir = current.relative_to(base)
            kept = []
            for name in sorted(dirnames):
                full = current / name
                if full.is_symlink():
                    result.skipped_links += 1
                    continue
                real = full.resolve()
                if real in excluded or real in walked_before or _matches(rel_dir / name, ignore):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in sorted(filenames):
                consider(current / name, index, rel_dir / name)
    return result


def _hash_partial(path: Path, size: int) -> Tuple[str, bool]:
    """Hash do começo e do fim. Para arquivos pequenos, é o hash do arquivo inteiro."""
    digest = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as fh:
        if size <= 2 * CHUNK:
            digest.update(fh.read())
            return digest.hexdigest(), True
        digest.update(fh.read(CHUNK))
        fh.seek(-CHUNK, os.SEEK_END)
        digest.update(fh.read(CHUNK))
    return digest.hexdigest(), False


def _hash_full(path: Path) -> str:
    digest = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicates(result: ScanResult, progress: Progress = None) -> List[DuplicateGroup]:
    """Agrupa por tamanho, filtra pelo hash parcial e confirma com o hash completo."""
    by_size: Dict[int, List[FileInfo]] = defaultdict(list)
    for info in result.files:
        by_size[info.size].append(info)
    candidates = [group for group in by_size.values() if len(group) > 1]
    total = sum(len(g) for g in candidates)
    done = 0
    groups: List[DuplicateGroup] = []

    def hashed(files: List[FileInfo], function) -> Dict[str, List[FileInfo]]:
        nonlocal done
        buckets: Dict[str, List[FileInfo]] = defaultdict(list)
        for info in files:
            try:
                buckets[function(info)].append(info)
            except OSError as exc:
                result.unreadable.append((info.path, describe_error(exc)))
            done += 1
            if progress:
                progress("conteudo", done, total)
        return buckets

    for same_size in candidates:
        complete: Dict[str, bool] = {}

        def partial(info: FileInfo) -> str:
            digest, whole = _hash_partial(info.path, info.size)
            complete[digest] = whole
            return digest

        for digest, same_partial in hashed(same_size, partial).items():
            if len(same_partial) < 2:
                continue
            if complete[digest]:
                groups.append(DuplicateGroup(same_partial[0].size, digest, same_partial))
                continue
            total += len(same_partial)
            for full, same_full in hashed(same_partial, lambda i: _hash_full(i.path)).items():
                if len(same_full) > 1:
                    groups.append(DuplicateGroup(same_full[0].size, full, same_full))
    groups.sort(key=lambda g: (-g.wasted, g.files[0].order))
    result.groups = groups
    return groups
