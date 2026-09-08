from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gerenciar_manutencao import liberar_lock, ler_lock, lock_ativo, salvar_lock


class ManutencaoTests(unittest.TestCase):
    def test_lock_ativo_e_liberado_somente_pelo_dono(self) -> None:
        momento = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "lock.json"
            with patch("gerenciar_manutencao.agora_utc", return_value=momento):
                salvar_lock("execucao-1", 60, caminho)
            self.assertTrue(lock_ativo(ler_lock(caminho), momento))
            with self.assertRaisesRegex(RuntimeError, "outra execução"):
                liberar_lock("execucao-2", caminho)
            liberar_lock("execucao-1", caminho)
            self.assertFalse(caminho.exists())

    def test_lock_corrompido_bloqueia(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "lock.json"
            caminho.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "corrompida"):
                ler_lock(caminho)

    def test_lock_expirado_nao_bloqueia(self) -> None:
        momento = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        dados = {
            "id": "antigo",
            "expira_em": (momento - timedelta(seconds=1)).isoformat(),
        }
        self.assertFalse(lock_ativo(dados, momento))


if __name__ == "__main__":
    unittest.main()
