from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from definir_janela import definir
from reivindicar import claim_esta_ativo, reivindicar_item


class JanelaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agora = datetime(2026, 9, 8, 9, 0, tzinfo=timezone(timedelta(hours=-3)))

    def test_cron_utc_mapeia_para_brasilia(self) -> None:
        self.assertEqual(
            definir("schedule", "0 12 * * *", "", "", "auto", "", self.agora),
            ("2026-09-08", "09:00", "ambos"),
        )
        agora_21h = datetime(
            2026, 9, 8, 21, 31, tzinfo=timezone(timedelta(hours=-3))
        )
        self.assertEqual(
            definir("schedule", "30 0 * * *", "", "", "auto", "", agora_21h),
            ("2026-09-08", "21:00", "reel"),
        )

    def test_cron_de_21h_atrasado_apos_meia_noite_nao_avanca_a_data(self) -> None:
        depois_da_meia_noite = datetime(
            2026, 9, 9, 0, 30, tzinfo=timezone(timedelta(hours=-3))
        )
        self.assertEqual(
            definir(
                "schedule", "0 0 * * *", "", "", "auto", "", depois_da_meia_noite
            ),
            ("2026-09-08", "21:00", "reel"),
        )

    def test_schedule_atrasado_mais_de_quatro_horas_e_bloqueado(self) -> None:
        muito_atrasado = datetime(
            2026, 9, 8, 20, 30, tzinfo=timezone(timedelta(hours=-3))
        )
        with self.assertRaisesRegex(RuntimeError, "atrasado"):
            definir("schedule", "0 8 * * *", "", "", "auto", "", muito_atrasado)

    def test_dispatch_externo_exige_janela_explicita(self) -> None:
        payload = '{"data":"2026-09-09","horario":"13:00","escopo":"reel"}'
        self.assertEqual(
            definir("repository_dispatch", "", "", "", "auto", payload, self.agora),
            ("2026-09-09", "13:00", "reel"),
        )


class ClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agora = datetime(2026, 9, 8, 9, 0, tzinfo=timezone(timedelta(hours=-3)))

    def test_claim_ativo_bloqueia_execucao_diferente(self) -> None:
        item: dict = {}
        self.assertTrue(reivindicar_item(item, "run-1", self.agora, 25))
        self.assertTrue(claim_esta_ativo(item, self.agora))
        self.assertFalse(reivindicar_item(item, "run-2", self.agora, 25))

    def test_mesmo_run_pode_retentar(self) -> None:
        item: dict = {}
        self.assertTrue(reivindicar_item(item, "run-1", self.agora, 25))
        self.assertTrue(reivindicar_item(item, "run-1", self.agora, 25))


if __name__ == "__main__":
    unittest.main()
