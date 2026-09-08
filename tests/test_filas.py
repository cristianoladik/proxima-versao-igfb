from __future__ import annotations

import unittest

from limpar_release import assets_elegiveis, validar_asset_remoto
from validar_filas import validar_reels, validar_stories


def midia(nome: str = "abc.mp4", duracao: float | None = None) -> dict:
    resultado = {
        "asset": nome,
        "url_publica": f"https://github.com/exemplo/repo/releases/download/fila/{nome}",
        "sha256": "a" * 64,
        "tamanho_bytes": 123,
        "duracao_segundos": 45.0,
        "largura": 1080,
        "altura": 1920,
        "fps": 30.0,
        "bitrate_video_bps": 5_000_000,
        "codec_video": "h264",
        "formato_pixel": "yuv420p",
    }
    if duracao is not None:
        resultado["duracao_segundos"] = duracao
    return resultado


class ValidacaoTests(unittest.TestCase):
    def test_filas_vazias_sao_validas(self) -> None:
        self.assertEqual(
            validar_reels(
                {
                    "versao_schema": 1,
                    "canal": "instagram-facebook-reels",
                    "conteudos": [],
                }
            ),
            0,
        )
        self.assertEqual(
            validar_stories(
                {
                    "versao_schema": 1,
                    "canal": "instagram-facebook-stories",
                    "pacotes": [],
                }
            ),
            (0, 0),
        )

    def test_story_acima_de_59_segundos_falha(self) -> None:
        fila = {
            "versao_schema": 1,
            "canal": "instagram-facebook-stories",
            "pacotes": [
                {
                    "id": "story-1",
                    "data": "2026-09-08",
                    "horario": "09:00",
                    "status": "pendente",
                    "partes": [
                        {
                            "ordem": 1,
                            "midia": midia(duracao=59.001),
                            "instagram": {"status": "pendente"},
                            "facebook": {"status": "pendente"},
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(RuntimeError):
            validar_stories(fila)

    def test_story_abaixo_de_3_segundos_falha(self) -> None:
        fila = {
            "versao_schema": 1,
            "canal": "instagram-facebook-stories",
            "pacotes": [
                {
                    "id": "story-curto",
                    "data": "2026-09-08",
                    "horario": "09:00",
                    "status": "pendente",
                    "partes": [
                        {
                            "ordem": 1,
                            "midia": midia(duracao=2.999),
                            "instagram": {"status": "pendente"},
                            "facebook": {"status": "pendente"},
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(RuntimeError):
            validar_stories(fila)

    def test_limpeza_seleciona_apenas_item_concluido(self) -> None:
        concluida = midia("ok.mp4")
        pendente = midia("pendente.mp4")
        fila = {
            "conteudos": [
                {"status": "concluido", "midia": concluida},
                {"status": "pendente", "midia": pendente},
            ]
        }
        self.assertEqual(assets_elegiveis(fila, {"pacotes": []}), {"ok.mp4": [concluida]})

    def test_limpeza_nao_apaga_asset_compartilhado_com_item_pendente(self) -> None:
        compartilhada_1 = midia("compartilhado.mp4")
        compartilhada_2 = midia("compartilhado.mp4")
        reels = {
            "conteudos": [
                {"status": "concluido", "midia": compartilhada_1},
                {"status": "pendente", "midia": compartilhada_2},
            ]
        }
        self.assertEqual(assets_elegiveis(reels, {"pacotes": []}), {})

    def test_limpeza_exige_sha_retornado_pela_release(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "SHA-256 válido"):
            validar_asset_remoto(
                "video.mp4",
                {"size": 123, "digest": ""},
                {"sha256": "a" * 64, "tamanho_bytes": 123},
            )


if __name__ == "__main__":
    unittest.main()
