"""Escolha da cópia a manter e ações sobre as demais: mover, apagar ou hardlink."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

from .scanner import DuplicateGroup, FileInfo, describe_error

STRATEGIES = ("mais-antigo", "mais-novo", "caminho-curto", "primeiro")
ACTIONS = ("mover", "apagar", "hardlink")

_KEYS = {
    "mais-antigo": lambda f: (f.mtime, f.order),
    "mais-novo": lambda f: (-f.mtime, f.order),
    "caminho-curto": lambda f: (len(f.path.parts), len(str(f.path)), f.order),
    # Primeira pasta informada; dentro dela, a cópia mais antiga.
    "primeiro": lambda f: (f.root, f.mtime, f.order),
}


def choose_keeper(files: Sequence[FileInfo], strategy: str = "mais-antigo") -> FileInfo:
    if strategy not in _KEYS:
        raise ValueError(f"estratégia desconhecida: {strategy}")
    return min(files, key=_KEYS[strategy])


@dataclass
class Action:
    kind: str
    duplicate: FileInfo
    keeper: FileInfo
    destination: Optional[Path] = None


@dataclass
class Outcome:
    done: List[Action] = field(default_factory=list)
    errors: List[Tuple[Action, str]] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(a.duplicate.size for a in self.done)


def root_labels(roots: Sequence[str]) -> List[str]:
    """Nome de cada pasta informada, usado como primeiro nível em --mover-para."""
    labels: List[str] = []
    used: Set[str] = set()
    for root in roots:
        resolved = Path(root).resolve()
        name = (resolved.name if resolved.is_dir() else resolved.parent.name) or "raiz"
        label, number = name, 2
        while label.casefold() in used:
            label, number = f"{name} ({number})", number + 1
        used.add(label.casefold())
        labels.append(label)
    return labels


def _free_path(path: Path, taken: Set[str]) -> Path:
    candidate, number = path, 1
    while os.path.lexists(candidate) or str(candidate).casefold() in taken:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    taken.add(str(candidate).casefold())
    return candidate


def plan_actions(
    groups: Sequence[DuplicateGroup],
    kind: str,
    strategy: str = "mais-antigo",
    roots: Sequence[str] = (),
    move_to: Optional[str] = None,
) -> Tuple[List[Action], List[Tuple[FileInfo, str]]]:
    """Uma ação para cada cópia extra; a cópia escolhida para ficar nunca entra no plano."""
    if kind not in ACTIONS:
        raise ValueError(f"ação desconhecida: {kind}")
    labels = root_labels(roots) if kind == "mover" else []
    taken: Set[str] = set()
    actions: List[Action] = []
    skipped: List[Tuple[FileInfo, str]] = []
    for group in groups:
        keeper = choose_keeper(group.files, strategy)
        for duplicate in group.files:
            if duplicate is keeper:
                continue
            if kind == "hardlink" and duplicate.dev != keeper.dev:
                skipped.append((duplicate, "está em outro disco ou partição; hardlink só funciona no mesmo sistema de arquivos"))
                continue
            destination = None
            if kind == "mover":
                destination = _free_path(Path(move_to) / labels[duplicate.root] / duplicate.rel, taken)
            actions.append(Action(kind, duplicate, keeper, destination))
    return actions, skipped


def _changed(info: FileInfo) -> Optional[str]:
    """Confere se o arquivo continua como na análise (existe, mesmo tamanho e data)."""
    try:
        st = os.lstat(info.path)
    except OSError as exc:
        return describe_error(exc)
    if stat.S_ISLNK(st.st_mode) or st.st_size != info.size or st.st_mtime != info.mtime:
        return "o arquivo mudou desde a análise"
    return None


def _same_file(a: Path, b: Path) -> bool:
    try:
        if os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _replace_with_hardlink(target: Path, source: Path) -> None:
    temp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.caca-duplicados")
    os.link(source, temp)
    try:
        os.replace(temp, target)  # troca atômica: o arquivo nunca deixa de existir
    except BaseException:
        os.remove(temp)
        raise


def execute(actions: Sequence[Action]) -> Outcome:
    outcome = Outcome()
    for action in actions:
        keeper, duplicate = action.keeper, action.duplicate
        problem = _changed(keeper)
        if problem:
            outcome.errors.append((action, f"a cópia mantida ({keeper.path}) não está mais igual: {problem}; nada foi feito"))
            continue
        problem = _changed(duplicate)
        if problem:
            outcome.errors.append((action, problem))
            continue
        if _same_file(duplicate.path, keeper.path):
            outcome.errors.append((action, "é o mesmo arquivo que a cópia mantida; nada foi feito"))
            continue
        try:
            if action.kind == "apagar":
                os.remove(duplicate.path)
            elif action.kind == "hardlink":
                _replace_with_hardlink(duplicate.path, keeper.path)
            else:
                destination = action.destination
                destination.parent.mkdir(parents=True, exist_ok=True)
                if os.path.lexists(destination):
                    destination = _free_path(destination, set())
                    action.destination = destination
                shutil.move(str(duplicate.path), str(destination))
            outcome.done.append(action)
        except OSError as exc:
            outcome.errors.append((action, describe_error(exc)))
    return outcome
