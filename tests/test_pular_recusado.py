import unittest

from fila_utils import (
    MAX_TENTATIVAS_ANTES_DE_PULAR,
    esgotou_tentativas,
    localizar_reel,
    pular_e_puxar_proximo,
)


def _reel(id_, data, horario, status="pendente", ig_status="pendente", tentativas=0):
    return {
        "id": id_, "data": data, "horario": horario, "status": status,
        "instagram": {"status": ig_status, "tentativas": tentativas},
        "facebook": {"status": "pendente", "tentativas": 0},
    }


class PularRecusadoTests(unittest.TestCase):
    def test_so_esgota_no_maximo_de_tentativas(self):
        item = _reel("a", "2026-09-15", "05:00", ig_status="erro", tentativas=MAX_TENTATIVAS_ANTES_DE_PULAR - 1)
        self.assertFalse(esgotou_tentativas([item], ("instagram", "facebook")))
        item["instagram"]["tentativas"] = MAX_TENTATIVAS_ANTES_DE_PULAR
        self.assertTrue(esgotou_tentativas([item], ("instagram", "facebook")))

    def test_proximo_pendente_assume_o_horario_e_o_pulado_sai_da_vez(self):
        recusado = _reel("a", "2026-09-15", "05:00", ig_status="erro", tentativas=3)
        recusado["execucao"] = {"id": "run-1"}
        fila = {"conteudos": [
            recusado,
            _reel("c", "2026-09-16", "05:00"),
            _reel("b", "2026-09-15", "13:00"),
            _reel("z", "2026-09-14", "21:00", status="concluido"),
        ]}
        proximo = pular_e_puxar_proximo(fila, "conteudos", recusado, "2026-09-15", "05:00")
        self.assertEqual(proximo["id"], "b")
        self.assertEqual((proximo["data"], proximo["horario"]), ("2026-09-15", "05:00"))
        self.assertEqual(proximo["reagendado_de"], "2026-09-15 13:00")
        self.assertEqual(proximo["execucao"], {"id": "run-1"})
        self.assertEqual(recusado["status"], "pulado")
        self.assertNotIn("execucao", recusado)
        self.assertIs(localizar_reel(fila, "2026-09-15", "05:00"), proximo)

    def test_sem_proximo_pendente_devolve_none(self):
        recusado = _reel("a", "2026-09-15", "05:00", ig_status="erro", tentativas=3)
        fila = {"conteudos": [recusado]}
        self.assertIsNone(pular_e_puxar_proximo(fila, "conteudos", recusado, "2026-09-15", "05:00"))
        self.assertEqual(recusado["status"], "pulado")


if __name__ == "__main__":
    unittest.main()
