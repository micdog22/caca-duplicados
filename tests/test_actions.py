import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from caca_duplicados.actions import choose_keeper, execute, plan_actions, root_labels  # noqa: E402
from caca_duplicados.cli import main  # noqa: E402
from caca_duplicados.scanner import collect_files, find_duplicates  # noqa: E402
from helpers import TempDirTestCase  # noqa: E402

JAN = 1704110400  # 01/01/2024
FEB = 1706788800  # 01/02/2024
MAR = 1709294400  # 01/03/2024


def groups_for(*roots):
    return find_duplicates(collect_files([str(r) for r in roots]))


class KeepStrategyTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        data = b"mesmo conteudo" * 64
        self.make("A/copias/antigas/foto.jpg", data, JAN)
        self.make("B/foto.jpg", data, MAR)
        self.make("C/f.jpg", data, FEB)
        [self.group] = groups_for("B", "A", "C")

    def keeper(self, strategy):
        return choose_keeper(self.group.files, strategy).path.as_posix()

    def test_strategies(self):
        self.assertEqual(self.keeper("mais-antigo"), "A/copias/antigas/foto.jpg")
        self.assertEqual(self.keeper("mais-novo"), "B/foto.jpg")
        self.assertEqual(self.keeper("caminho-curto"), "C/f.jpg")
        self.assertEqual(self.keeper("primeiro"), "B/foto.jpg")  # primeira pasta informada

    def test_ties_follow_folder_order(self):
        for info in self.group.files:
            os.utime(info.path, (JAN, JAN))
        [group] = groups_for("C", "B", "A")
        self.assertEqual(choose_keeper(group.files, "mais-antigo").path.as_posix(), "C/f.jpg")

    def test_plan_never_includes_the_keeper(self):
        for strategy in ("mais-antigo", "mais-novo", "caminho-curto", "primeiro"):
            actions, _ = plan_actions([self.group], "apagar", strategy)
            keeper = choose_keeper(self.group.files, strategy)
            self.assertEqual(len(actions), 2)
            self.assertTrue(all(a.duplicate is not keeper and a.keeper is keeper for a in actions))

    def test_first_folder_then_oldest_inside_it(self):
        self.make("B/foto (2).jpg", b"mesmo conteudo" * 64, FEB)
        [group] = groups_for("B", "A", "C")
        self.assertEqual(choose_keeper(group.files, "primeiro").path.as_posix(), "B/foto (2).jpg")

    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):
            choose_keeper(self.group.files, "aleatorio")


class ActionTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.data = b"foto de viagem" * 100
        self.make("Fotos/2024/praia.jpg", self.data, JAN)
        self.make("Backup/2024/praia.jpg", self.data, FEB)
        self.make("Backup/copia/praia (1).jpg", self.data, MAR)
        self.make("Backup/unica.txt", b"sem copia")

    def test_dry_run_makes_no_changes(self):
        before = self.snapshot()
        for option in (["--apagar"], ["--hardlink"], ["--mover-para", "Quarentena"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["Fotos", "Backup", "--simular", *option])
            self.assertEqual(code, 0)
            self.assertEqual(self.snapshot(), before)

    def test_move_preserves_structure(self):
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "mover", "mais-antigo", ["Fotos", "Backup"], "Quarentena")
        outcome = execute(actions)
        self.assertEqual(outcome.errors, [])
        self.assertEqual(outcome.bytes, 2 * len(self.data))
        self.assertEqual([p for p, _ in self.snapshot()], [
            "Backup/unica.txt",
            "Fotos/2024/praia.jpg",
            "Quarentena/Backup/2024/praia.jpg",
            "Quarentena/Backup/copia/praia (1).jpg",
        ])

    def test_move_never_overwrites(self):
        self.make("Quarentena/Backup/2024/praia.jpg", b"ja estava aqui")
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "mover", "mais-antigo", ["Fotos", "Backup"], "Quarentena")
        execute(actions)
        self.assertEqual((self.root / "Quarentena/Backup/2024/praia.jpg").read_bytes(), b"ja estava aqui")
        self.assertEqual((self.root / "Quarentena/Backup/2024/praia (1).jpg").read_bytes(), self.data)

    def test_delete_keeps_one_copy(self):
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "apagar")
        outcome = execute(actions)
        self.assertEqual(len(outcome.done), 2)
        self.assertEqual([p for p, _ in self.snapshot()], ["Backup/unica.txt", "Fotos/2024/praia.jpg"])

    def test_hardlinks_share_inode(self):
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "hardlink")
        try:
            outcome = execute(actions)
        except NotImplementedError:
            self.skipTest("hardlinks indisponíveis")
        self.assertEqual(outcome.errors, [])
        inodes = {os.stat(self.root / p).st_ino for p in (
            "Fotos/2024/praia.jpg", "Backup/2024/praia.jpg", "Backup/copia/praia (1).jpg")}
        self.assertEqual(len(inodes), 1)
        self.assertEqual(os.stat(self.root / "Fotos/2024/praia.jpg").st_nlink, 3)
        self.assertEqual((self.root / "Backup/copia/praia (1).jpg").read_bytes(), self.data)
        self.assertEqual(sorted(p.name for p in (self.root / "Backup" / "copia").iterdir()), ["praia (1).jpg"])

    def test_hardlink_across_devices_is_skipped(self):
        [group] = groups_for("Fotos", "Backup")
        group.files[1] = replace(group.files[1], dev=group.files[1].dev + 1)
        actions, skipped = plan_actions([group], "hardlink")
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(skipped), 1)
        self.assertIn("outro disco", skipped[0][1])

    def test_changed_keeper_protects_the_copies(self):
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "apagar")
        keeper = self.root / "Fotos/2024/praia.jpg"
        keeper.write_bytes(b"editada depois da analise")
        outcome = execute(actions)
        self.assertEqual(outcome.done, [])
        self.assertEqual(len(outcome.errors), 2)
        self.assertTrue((self.root / "Backup/2024/praia.jpg").exists())
        self.assertTrue((self.root / "Backup/copia/praia (1).jpg").exists())

    def test_changed_or_missing_duplicate_is_skipped(self):
        actions, _ = plan_actions(groups_for("Fotos", "Backup"), "apagar")
        (self.root / "Backup/2024/praia.jpg").unlink()
        os.utime(self.root / "Backup/copia/praia (1).jpg", (MAR + 60, MAR + 60))
        outcome = execute(actions)
        self.assertEqual(outcome.done, [])
        self.assertEqual(sorted(reason for _, reason in outcome.errors),
                         ["o arquivo mudou desde a análise", "o arquivo não existe mais"])

    def test_root_labels_are_unique(self):
        (self.root / "a" / "Fotos").mkdir(parents=True)
        (self.root / "b" / "Fotos").mkdir(parents=True)
        self.assertEqual(root_labels(["a/Fotos", "b/Fotos", "Backup"]), ["Fotos", "Fotos (2)", "Backup"])


if __name__ == "__main__":
    unittest.main()
