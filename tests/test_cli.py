import csv
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from caca_duplicados import __version__  # noqa: E402
from caca_duplicados.cli import main  # noqa: E402
from helpers import TempDirTestCase  # noqa: E402


def run(*args, answer=""):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch.object(sys, "stdin", io.StringIO(answer)):
        try:
            code = main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.make("Fotos/praia.jpg", b"praia" * 300, 1704110400)
        self.make("Downloads/praia (1).jpg", b"praia" * 300, 1706788800)
        self.make("Downloads/contrato.pdf", b"contrato" * 10)

    def test_report_and_exit_codes(self):
        code, out, _ = run("Fotos", "Downloads")
        self.assertEqual(code, 1)
        self.assertIn("Grupo 1 · 2 arquivos iguais de 1,5 KB · 1,5 KB desperdiçados", out)
        self.assertIn("manter  Fotos/praia.jpg", out)
        self.assertIn("cópia   Downloads/praia (1).jpg", out)
        self.assertIn("Espaço que pode ser liberado: 1,5 KB.", out)
        code, out, _ = run("Fotos")
        self.assertEqual(code, 0)
        self.assertIn("Nenhum duplicado encontrado entre 1 arquivo.", out)

    def test_json_and_csv(self):
        code, out, _ = run("Fotos", "Downloads", "--formato", "json", "--manter", "mais-novo")
        self.assertEqual(code, 1)
        data = json.loads(out)
        files = data["grupos"][0]["arquivos"]
        self.assertEqual([f["manter"] for f in files], [False, True])
        self.assertEqual(data["resumo"]["espaco_recuperavel"], 1500)
        self.assertEqual(data["resumo"]["estrategia"], "mais-novo")
        code, out, _ = run("Fotos", "Downloads", "-f", "csv")
        rows = list(csv.reader(io.StringIO(out), delimiter=";"))
        self.assertEqual(rows[0], ["grupo", "hash", "tamanho_bytes", "tamanho", "caminho", "modificado", "manter"])
        self.assertEqual([r[-1] for r in rows[1:]], ["sim", "não"])

    def test_delete_asks_for_confirmation(self):
        before = self.snapshot()
        code, out, err = run("Fotos", "Downloads", "--apagar", answer="n\n")
        self.assertEqual(code, 1)
        self.assertIn("Isso não pode ser desfeito", err)
        self.assertIn("Nada foi alterado.", out)
        self.assertEqual(self.snapshot(), before)
        code, _, _ = run("Fotos", "Downloads", "--apagar")  # sem resposta também cancela
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)

    def test_delete_with_yes(self):
        code, out, _ = run("Fotos", "Downloads", "--apagar", "-s")
        self.assertEqual(code, 0)
        self.assertIn("Pronto: 1 cópia apagada, 1,5 KB liberados.", out)
        self.assertEqual([p for p, _ in self.snapshot()], ["Downloads/contrato.pdf", "Fotos/praia.jpg"])

    def test_move_with_json_keeps_stdout_clean(self):
        code, out, err = run("Fotos", "Downloads", "--mover-para", "Quarentena", "-s", "-f", "json")
        self.assertEqual(code, 0)
        json.loads(out)
        self.assertIn("Pronto: 1 cópia movida para Quarentena", err)
        self.assertTrue((self.root / "Quarentena/Downloads/praia (1).jpg").exists())

    def test_usage_errors(self):
        code, _, err = run("Fotos", "--min-tamanho", "muito")
        self.assertEqual(code, 2)
        self.assertIn("tamanho inválido", err)
        code, _, err = run("nao-existe")
        self.assertEqual(code, 2)
        self.assertIn("não encontrado: nao-existe", err)
        code, _, err = run("Fotos", "--apagar", "--hardlink")
        self.assertEqual(code, 2)
        self.assertIn("não pode ser usado junto com", err)
        code, _, err = run("Fotos", "--mover-para", "Downloads/contrato.pdf")
        self.assertEqual(code, 2)
        self.assertIn("precisa ser uma pasta", err)
        for destination in (".", "Fotos"):
            code, _, err = run("Fotos", "Downloads", "--mover-para", destination, "-s")
            self.assertEqual(code, 2)
            self.assertIn("não pode ser uma das pastas analisadas", err)
        self.assertTrue((self.root / "Downloads/praia (1).jpg").exists())

    def test_filters_from_command_line(self):
        code, out, _ = run("Fotos", "Downloads", "--min-tamanho", "2K")
        self.assertEqual(code, 0)
        code, out, _ = run("Fotos", "Downloads", "--extensoes", "pdf")
        self.assertEqual(code, 0)
        code, out, _ = run("Fotos", "Downloads", "--ignorar", "*(1)*")
        self.assertEqual(code, 0)

    def test_version(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)


if __name__ == "__main__":
    unittest.main()
