from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import publicar
import publicar_stories


class RetomadaInstagramTests(unittest.TestCase):
    def test_reel_publicado_com_resposta_perdida_nao_chama_publish_de_novo(self) -> None:
        item = {
            "id": "reel-1",
            "midia": {"url_publica": "https://github.com/exemplo/video.mp4"},
            "instagram": {
                "status": "erro",
                "legenda": "Siga @pagina.",
                "container_id": "123",
                "fase_api": "publicacao_pendente_confirmacao",
            },
        }
        checkpoints: list[str] = []
        with (
            patch.dict(
                os.environ,
                {"IG_ACCESS_TOKEN": "token-teste", "IG_BUSINESS_ID": "ig-1"},
                clear=False,
            ),
            patch.object(
                publicar, "reconciliar_publicacao_instagram", return_value="PUBLISHED"
            ),
            patch.object(publicar, "graph_post") as post,
        ):
            identificador = publicar.publicar_instagram(item, checkpoints.append)
        self.assertEqual(identificador, "123")
        self.assertEqual(item["instagram"]["id_tipo"], "container_id_publicacao_reconciliada")
        post.assert_not_called()
        self.assertTrue(checkpoints)

    def test_story_salva_container_antes_do_media_publish(self) -> None:
        parte = {
            "ordem": 1,
            "midia": {"url_publica": "https://github.com/exemplo/story.mp4"},
            "instagram": {"status": "pendente"},
        }
        estados: list[str] = []

        def checkpoint(_: str) -> None:
            estados.append(str(parte["instagram"].get("fase_api")))

        with (
            patch.dict(
                os.environ,
                {"IG_ACCESS_TOKEN": "token-teste", "IG_BUSINESS_ID": "ig-1"},
                clear=False,
            ),
            patch.object(
                publicar_stories,
                "graph_post",
                side_effect=({"id": "container-1"}, {"id": "story-1"}),
            ),
            patch.object(
                publicar_stories, "aguardar_container_instagram", return_value="FINISHED"
            ),
        ):
            identificador = publicar_stories.publicar_instagram(parte, checkpoint)

        self.assertEqual(identificador, "story-1")
        self.assertEqual(
            estados,
            ["container_criado", "publicacao_pendente_confirmacao", "publicado_confirmado"],
        )


class RetomadaFacebookTests(unittest.TestCase):
    def test_finish_ambiguo_confirmado_reutiliza_video_id(self) -> None:
        item = {
            "id": "reel-2",
            "midia": {},
            "facebook": {
                "status": "erro",
                "legenda": "Siga @pagina.",
                "video_id": "video-1",
                "fase_api": "finalizacao_pendente_confirmacao",
            },
        }
        with (
            patch.object(publicar, "token_pagina_facebook", return_value=("token", "page")),
            patch.object(publicar, "aguardar_video_facebook", return_value={}),
            patch.object(publicar, "graph_post") as post,
        ):
            identificador = publicar.publicar_facebook(item, lambda _: None)
        self.assertEqual(identificador, "video-1")
        post.assert_not_called()

    def test_upload_incompleto_abre_nova_sessao_sem_gravar_upload_url(self) -> None:
        item = {
            "id": "reel-3",
            "midia": {},
            "facebook": {
                "status": "erro",
                "legenda": "Siga @pagina.",
                "video_id": "video-antigo",
                "fase_api": "upload_iniciado",
            },
        }
        resposta_upload = Mock(ok=True)
        resposta_upload.text = ""
        with tempfile.TemporaryDirectory() as pasta:
            video = Path(pasta) / "video.mp4"
            video.write_bytes(b"conteudo")
            with (
                patch.object(
                    publicar, "token_pagina_facebook", return_value=("token", "page")
                ),
                patch.object(
                    publicar,
                    "consultar_video_facebook",
                    return_value={
                        "status": {
                            "uploading_phase": {
                                "status": "in_progress",
                                "bytes_transfered": 2,
                                "source_file_size": 8,
                            }
                        }
                    },
                ),
                patch.object(publicar, "baixar_midia", return_value=video),
                patch.object(
                    publicar,
                    "graph_post",
                    side_effect=(
                        {"video_id": "video-novo", "upload_url": "https://upload.invalid"},
                        {"success": True},
                    ),
                ),
                patch.object(publicar.requests, "post", return_value=resposta_upload),
                patch.object(publicar, "aguardar_video_facebook", return_value={}),
            ):
                identificador = publicar.publicar_facebook(item, lambda _: None)

        self.assertEqual(identificador, "video-novo")
        self.assertEqual(item["facebook"]["uploads_abandonados"], ["video-antigo"])
        self.assertNotIn("upload_url", item["facebook"])

    def test_story_nao_conclui_sem_comprovante_exato_na_colecao_da_pagina(self) -> None:
        parte = {
            "ordem": 1,
            "midia": {},
            "facebook": {
                "status": "erro",
                "video_id": "video-story",
                "fase_api": "finalizacao_pendente_confirmacao",
            },
        }
        with (
            patch.object(
                publicar_stories,
                "token_pagina_facebook",
                return_value=("token", "page"),
            ),
            patch.object(publicar_stories, "localizar_story_facebook", return_value=None),
            patch.object(publicar_stories, "aguardar_video_facebook", return_value={}),
            patch.object(
                publicar_stories,
                "aguardar_story_facebook",
                side_effect=TimeoutError("sem comprovante"),
            ),
            patch.object(publicar_stories, "graph_post") as post,
        ):
            with self.assertRaisesRegex(TimeoutError, "sem comprovante"):
                publicar_stories.publicar_facebook(parte, lambda _: None)
        self.assertNotIn("id", parte["facebook"])
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
