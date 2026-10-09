"""Linha de comando do caca-duplicados."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, TextIO

from . import __version__
from .actions import STRATEGIES, Action, execute, plan_actions
from .argparse_ptbr import ArgumentParser
from .report import number, plural, render_csv, render_json, render_text
from .scanner import collect_files, find_duplicates, normalize_extensions
from .sizes import format_size, parse_size

PROG = "caca-duplicados"

EPILOG = """\
exemplos:
  caca-duplicados ~/Fotos ~/Downloads
  caca-duplicados ~/Fotos --min-tamanho 1M --extensoes jpg,jpeg,heic,png
  caca-duplicados . --ignorar node_modules --ignorar "*.tmp" --formato csv > duplicados.csv
  caca-duplicados ~/Fotos ~/Backup --manter primeiro --mover-para ~/Quarentena --simular
  caca-duplicados ~/Fotos --apagar

códigos de saída: 0 nenhum duplicado (ou ação concluída), 1 duplicados encontrados
(ou ação cancelada/com erro), 2 uso incorreto.
"""


def _size(text: str) -> int:
    try:
        return parse_size(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(
        prog=PROG,
        description=(
            "Encontra arquivos duplicados (mesmo conteúdo, qualquer nome) e mostra quanto\n"
            "espaço dá para liberar. Se você pedir, move, apaga ou troca as cópias\n"
            "por hardlinks."
        ),
        epilog=EPILOG,
    )
    parser.add_argument("pastas", nargs="+", metavar="PASTA", help="pastas (ou arquivos) a analisar")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}", help="mostra a versão e sai")

    filters = parser.add_argument_group("filtros")
    filters.add_argument("--min-tamanho", type=_size, default=0, metavar="TAM",
                         help="ignora arquivos menores que TAM, ex.: 100K, 1,5M, 2G")
    filters.add_argument("--incluir-vazios", action="store_true", help="também compara arquivos vazios (ignorados por padrão)")
    filters.add_argument("--ignorar", action="append", default=[], metavar="PADRÃO",
                         help="ignora arquivos ou pastas que casam com o padrão (pode repetir), ex.: '*.tmp'")
    filters.add_argument("--extensoes", metavar="LISTA", help="compara só estas extensões, ex.: jpg,png,heic")

    output = parser.add_argument_group("relatório")
    output.add_argument("-f", "--formato", choices=("texto", "json", "csv"), default="texto", help="formato do relatório (padrão: texto)")
    output.add_argument("--manter", choices=STRATEGIES, default="mais-antigo",
                        help="qual cópia fica: mais-antigo (padrão), mais-novo, caminho-curto ou "
                        "primeiro (na ordem das pastas informadas)")

    actions = parser.add_argument_group("ações (opcionais; só uma por vez)")
    exclusive = actions.add_mutually_exclusive_group()
    exclusive.add_argument("--mover-para", metavar="PASTA",
                           help="move as cópias extras para PASTA mantendo a estrutura de pastas (a opção mais segura)")
    exclusive.add_argument("--apagar", action="store_true", help="apaga as cópias extras")
    exclusive.add_argument("--hardlink", action="store_true",
                           help="troca as cópias extras por hardlinks da cópia mantida (só no mesmo disco)")
    actions.add_argument("-n", "--simular", action="store_true", help="mostra o que seria feito, sem alterar nada")
    actions.add_argument("-s", "--sim", action="store_true", help="não pede confirmação")
    return parser


class ProgressLine:
    """Progresso no stderr, só quando é um terminal."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.last = 0.0
        self.used = False

    def __call__(self, stage: str, done: int, total: int) -> None:
        now = time.monotonic()
        if now - self.last < 0.1 and done != total:
            return
        self.last = now
        self.used = True
        if stage == "arquivos":
            text = f"Procurando arquivos: {number(done)}"
        else:
            text = f"Comparando conteúdo: {number(done)} de {number(total)}"
        self.stream.write("\r" + text.ljust(60))
        self.stream.flush()

    def clear(self) -> None:
        if self.used:
            self.stream.write("\r" + " " * 60 + "\r")
            self.stream.flush()


def confirm(question: str) -> bool:
    sys.stderr.write(f"{question} [s/N] ")
    sys.stderr.flush()
    answer = sys.stdin.readline()
    if not answer:
        sys.stderr.write("\n")
        return False
    return answer.strip().lower() in ("s", "sim", "y", "yes")


def _describe(action: Action) -> str:
    if action.kind == "apagar":
        return f"  apagaria  {action.duplicate.path}  (igual a {action.keeper.path})"
    if action.kind == "mover":
        return f"  moveria   {action.duplicate.path} -> {action.destination}"
    return f"  hardlink  {action.duplicate.path} -> {action.keeper.path}"


def _question(kind: str, count: int, size: int, destination: Optional[str]) -> str:
    copies = plural(count, "cópia extra", "cópias extras")
    if kind == "apagar":
        return f"Apagar {copies} ({format_size(size)})? Isso não pode ser desfeito."
    if kind == "mover":
        return f"Mover {copies} ({format_size(size)}) para {destination}?"
    return f"Trocar {copies} por hardlinks e liberar {format_size(size)}?"


def _done_message(kind: str, count: int, size: int, destination: Optional[str]) -> str:
    if kind == "apagar":
        return f"Pronto: {plural(count, 'cópia apagada', 'cópias apagadas')}, {format_size(size)} liberados."
    if kind == "mover":
        return f"Pronto: {plural(count, 'cópia movida', 'cópias movidas')} para {destination} ({format_size(size)})."
    replaced = plural(count, "cópia trocada por hardlink", "cópias trocadas por hardlinks")
    return f"Pronto: {replaced}, {format_size(size)} liberados."


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    missing = [p for p in args.pastas if not os.path.exists(p)]
    if missing:
        parser.error(f"não encontrado: {', '.join(missing)}")
    destination = Path(args.mover_para).expanduser() if args.mover_para else None
    if destination is not None:
        if destination.exists() and not destination.is_dir():
            parser.error(f"--mover-para precisa ser uma pasta: {args.mover_para}")
        target = destination.resolve()
        roots = [Path(p).resolve() for p in args.pastas]
        if any(target == r or target in r.parents for r in roots):
            parser.error("a pasta de --mover-para não pode ser uma das pastas analisadas nem conter alguma delas")

    progress = ProgressLine(sys.stderr) if sys.stderr.isatty() else None
    try:
        result = collect_files(
            args.pastas,
            min_size=args.min_tamanho,
            include_empty=args.incluir_vazios,
            ignore=args.ignorar,
            extensions=normalize_extensions(args.extensoes),
            exclude=[destination] if destination else [],
            progress=progress,
        )
        groups = find_duplicates(result, progress)
    except KeyboardInterrupt:
        if progress:
            progress.clear()
        print("Interrompido.", file=sys.stderr)
        return 130
    if progress:
        progress.clear()
    for path, reason in result.unreadable:
        print(f"aviso: não foi possível ler {path}: {reason}", file=sys.stderr)

    if args.formato == "json":
        sys.stdout.write(render_json(groups, result, args.manter))
    elif args.formato == "csv":
        sys.stdout.write(render_csv(groups, args.manter))
    else:
        sys.stdout.write(render_text(groups, result, args.manter))
    sys.stdout.flush()

    kind = "mover" if destination else "apagar" if args.apagar else "hardlink" if args.hardlink else None
    if kind is None:
        return 1 if groups else 0
    if not groups:
        return 0

    out = sys.stdout if args.formato == "texto" else sys.stderr
    actions, skipped = plan_actions(groups, kind, args.manter, args.pastas, str(destination) if destination else None)
    for info, reason in skipped:
        print(f"aviso: {info.path} fica como está: {reason}", file=out)
    if not actions:
        print("Nada a fazer.", file=out)
        return 1 if skipped else 0
    total = sum(a.duplicate.size for a in actions)
    print(file=out)
    if args.simular:
        for action in actions:
            print(_describe(action), file=out)
        print(f"\nSimulação: {plural(len(actions), 'cópia extra', 'cópias extras')} ({format_size(total)}); "
              "nada foi alterado.", file=out)
        return 0
    if not args.sim and not confirm(_question(kind, len(actions), total, args.mover_para)):
        print("Nada foi alterado.", file=out)
        return 1

    outcome = execute(actions)
    if outcome.done:
        print(_done_message(kind, len(outcome.done), outcome.bytes, args.mover_para), file=out)
    if outcome.errors:
        print(f"Não foi possível tratar {plural(len(outcome.errors), 'arquivo', 'arquivos')}:", file=out)
        for action, reason in outcome.errors:
            print(f"  {action.duplicate.path}: {reason}", file=out)
    return 1 if outcome.errors else 0
