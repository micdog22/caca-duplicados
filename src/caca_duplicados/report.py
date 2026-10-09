"""Relatórios: texto para ler no terminal, JSON e CSV para planilhas e scripts."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import List, Sequence

from .actions import choose_keeper
from .scanner import DuplicateGroup, ScanResult
from .sizes import format_size


def number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{number(count)} {singular if count == 1 else plural_form}"


def _date_br(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")


def _date_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def summary(groups: Sequence[DuplicateGroup], result: ScanResult) -> dict:
    return {
        "arquivos_analisados": len(result.files),
        "grupos": len(groups),
        "copias_extras": sum(len(g.files) - 1 for g in groups),
        "espaco_recuperavel": sum(g.wasted for g in groups),
    }


def render_text(groups: Sequence[DuplicateGroup], result: ScanResult, strategy: str) -> str:
    lines: List[str] = []
    for index, group in enumerate(groups, 1):
        keeper = choose_keeper(group.files, strategy)
        lines.append(
            f"Grupo {index} · {len(group.files)} arquivos iguais de {format_size(group.size)}"
            f" · {format_size(group.wasted)} desperdiçados"
        )
        for info in group.files:
            label = "manter" if info is keeper else "cópia "
            lines.append(f"  {label}  {info.path}  ({_date_br(info.mtime)})")
        lines.append("")
    s = summary(groups, result)
    if groups:
        lines.append(
            f"{plural(s['arquivos_analisados'], 'arquivo analisado', 'arquivos analisados')}: "
            f"{plural(s['grupos'], 'grupo', 'grupos')} de duplicados, "
            f"{plural(s['copias_extras'], 'cópia extra', 'cópias extras')}."
        )
        lines.append(f"Espaço que pode ser liberado: {format_size(s['espaco_recuperavel'])}.")
    else:
        lines.append(f"Nenhum duplicado encontrado entre {plural(s['arquivos_analisados'], 'arquivo', 'arquivos')}.")
    skipped = []
    if result.skipped_empty:
        skipped.append(plural(result.skipped_empty, "vazio", "vazios"))
    if result.skipped_links:
        skipped.append(plural(result.skipped_links, "link simbólico", "links simbólicos"))
    if result.skipped_filtered:
        skipped.append(f"{number(result.skipped_filtered)} pelos filtros")
    if result.same_inode:
        skipped.append(plural(result.same_inode, "hardlink de arquivo já analisado", "hardlinks de arquivos já analisados"))
    if skipped:
        lines.append(f"Ignorados: {', '.join(skipped)}.")
    return "\n".join(lines) + "\n"


def render_json(groups: Sequence[DuplicateGroup], result: ScanResult, strategy: str) -> str:
    data_groups = []
    for group in groups:
        keeper = choose_keeper(group.files, strategy)
        data_groups.append({
            "tamanho": group.size,
            "tamanho_legivel": format_size(group.size),
            "hash": group.digest,
            "desperdicio": group.wasted,
            "arquivos": [
                {"caminho": str(f.path), "modificado": _date_iso(f.mtime), "manter": f is keeper}
                for f in group.files
            ],
        })
    s = summary(groups, result)
    s["espaco_recuperavel_legivel"] = format_size(s["espaco_recuperavel"])
    s["estrategia"] = strategy
    s["nao_lidos"] = [{"caminho": str(p), "motivo": reason} for p, reason in result.unreadable]
    return json.dumps({"grupos": data_groups, "resumo": s}, ensure_ascii=False, indent=2) + "\n"


def render_csv(groups: Sequence[DuplicateGroup], strategy: str, separator: str = ";") -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=separator, lineterminator="\r\n")
    writer.writerow(["grupo", "hash", "tamanho_bytes", "tamanho", "caminho", "modificado", "manter"])
    for index, group in enumerate(groups, 1):
        keeper = choose_keeper(group.files, strategy)
        for f in group.files:
            writer.writerow([
                index, group.digest, group.size, format_size(group.size),
                str(f.path), _date_iso(f.mtime), "sim" if f is keeper else "não",
            ])
    return buffer.getvalue()
