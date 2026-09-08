"""Publica, em ordem, todas as partes do pacote de Stories reivindicado."""

from __future__ import annotations

import os
from typing import Any, Callable

import requests

from fila_utils import (
    FILA_STORIES,
    PLATAFORMAS,
    agora_brasilia,
    carregar,
    checkpoint as salvar_checkpoint,
    localizar_story,
    reivindicacao_valida,
    salvar,
)
from meta_api import (
    aguardar_container_instagram,
    aguardar_story_facebook,
    aguardar_video_facebook,
    baixar_midia,
    consultar_video_facebook,
    graph_post,
    localizar_story_facebook,
    obrigatoria,
    reconciliar_publicacao_instagram,
    token_pagina_facebook,
    verificar_capacidade_instagram,
)


Checkpoint = Callable[[str], None]
Publicador = Callable[[dict[str, Any], Checkpoint], str]


def publicar_instagram(parte: dict[str, Any], checkpoint: Checkpoint) -> str:
    dados = parte["instagram"]
    if dados.get("id"):
        return str(dados["id"])
    token = obrigatoria("IG_ACCESS_TOKEN")
    ig_id = obrigatoria("IG_BUSINESS_ID")
    container_id = dados.get("container_id")
    fase = str(dados.get("fase_api", ""))
    if container_id and fase == "publicacao_pendente_confirmacao":
        estado = reconciliar_publicacao_instagram(str(container_id), token)
        if estado == "PUBLISHED":
            dados["id"] = str(container_id)
            dados["id_tipo"] = "container_id_publicacao_reconciliada"
            dados["fase_api"] = "publicado_confirmado"
            checkpoint(f"Story Instagram parte {parte['ordem']} reconciliada")
            return str(container_id)
        if estado != "FINISHED":
            raise RuntimeError(
                f"Estado inconclusivo do container Instagram {container_id}: {estado!r}."
            )
    if container_id and fase == "publicado_confirmado":
        raise RuntimeError("Container de Story marcado como publicado, mas sem ID final.")
    if not container_id:
        container = graph_post(
            f"{ig_id}/media",
            {
                "media_type": "STORIES",
                "video_url": parte["midia"]["url_publica"],
                "access_token": token,
            },
        )
        container_id = container.get("id")
        if not container_id:
            raise RuntimeError(f"Container do Story no Instagram sem ID: {container}")
        dados["container_id"] = str(container_id)
        dados["fase_api"] = "container_criado"
        checkpoint(f"Story Instagram parte {parte['ordem']} container")
    estado = aguardar_container_instagram(str(container_id), token)
    if estado == "PUBLISHED":
        dados["id"] = str(container_id)
        dados["id_tipo"] = "container_id_publicacao_reconciliada"
        dados["fase_api"] = "publicado_confirmado"
        checkpoint(f"Story Instagram parte {parte['ordem']} reconciliada")
        return str(container_id)
    dados["fase_api"] = "publicacao_pendente_confirmacao"
    checkpoint(f"Story Instagram parte {parte['ordem']} antes de publicar")
    publicado = graph_post(
        f"{ig_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
    )
    if not publicado.get("id"):
        raise RuntimeError(f"O Instagram não retornou o Story publicado: {publicado}")
    dados["id"] = str(publicado["id"])
    dados["fase_api"] = "publicado_confirmado"
    checkpoint(f"Story Instagram parte {parte['ordem']} publicada")
    return str(dados["id"])


def publicar_facebook(parte: dict[str, Any], checkpoint: Checkpoint) -> str:
    dados = parte["facebook"]
    if dados.get("id"):
        return str(dados["id"])
    token, page_id = token_pagina_facebook()
    video_id = dados.get("video_id")
    fase = str(dados.get("fase_api", ""))

    if video_id and fase in {"finalizacao_pendente_confirmacao", "finish_aceito"}:
        story = localizar_story_facebook(page_id, str(video_id), token)
        if (
            story
            and str(story.get("status", "")).upper() in {"PUBLISHED", "ARCHIVED"}
            and story.get("post_id")
        ):
            dados["id"] = str(story.get("post_id") or video_id)
            dados["media_id"] = str(video_id)
            dados["fase_api"] = "publicado_confirmado"
            checkpoint(f"Story Facebook parte {parte['ordem']} reconciliada")
            return str(dados["id"])
        try:
            aguardar_video_facebook(str(video_id), token)
        except TimeoutError:
            if fase == "finish_aceito":
                raise
            dados["fase_api"] = "upload_concluido"
            checkpoint(f"Story Facebook parte {parte['ordem']} finish reconciliado")
            fase = "upload_concluido"
        else:
            story = aguardar_story_facebook(page_id, str(video_id), token)
            dados["id"] = str(story["post_id"])
            dados["media_id"] = str(video_id)
            dados["fase_api"] = "publicado_confirmado"
            checkpoint(f"Story Facebook parte {parte['ordem']} reconciliada")
            return str(dados["id"])

    if video_id and fase == "publicado_confirmado":
        dados["id"] = str(dados.get("post_id") or video_id)
        checkpoint(f"Story Facebook parte {parte['ordem']} ID restaurado")
        return str(dados["id"])

    if video_id and fase == "upload_iniciado":
        estado = consultar_video_facebook(str(video_id), token).get("status", {}) or {}
        upload = estado.get("uploading_phase") or {}
        status_upload = str(upload.get("status", "")).lower()
        transferidos = int(upload.get("bytes_transfered", 0) or 0)
        total_remoto = int(upload.get("source_file_size", 0) or 0)
        if status_upload in {"complete", "completed"} or (
            total_remoto > 0 and transferidos >= total_remoto
        ):
            dados["fase_api"] = "upload_concluido"
            checkpoint(f"Story Facebook parte {parte['ordem']} upload reconciliado")
            fase = "upload_concluido"
        else:
            dados.setdefault("uploads_abandonados", []).append(str(video_id))
            dados.pop("video_id", None)
            dados.pop("fase_api", None)
            checkpoint(f"Story Facebook parte {parte['ordem']} upload incompleto abandonado")
            video_id = None
            fase = ""

    if video_id and fase not in {"upload_concluido"}:
        raise RuntimeError(f"Estado de retomada desconhecido do Story no Facebook: {fase!r}.")

    caminho = None
    try:
        if not video_id:
            caminho = baixar_midia(parte["midia"])
            inicio = graph_post(
                f"{page_id}/video_stories",
                {"upload_phase": "start", "access_token": token},
            )
            video_id = inicio.get("video_id")
            upload_url = inicio.get("upload_url")
            if not video_id or not upload_url:
                raise RuntimeError(f"O Facebook não iniciou o upload do Story: {inicio}")
            dados["video_id"] = str(video_id)
            dados["fase_api"] = "upload_iniciado"
            checkpoint(f"Story Facebook parte {parte['ordem']} upload iniciado")
            offset = 0
        else:
            offset = None

        if offset is not None:
            tamanho = caminho.stat().st_size
            if offset < 0 or offset > tamanho:
                raise RuntimeError(
                    f"Offset remoto inválido para o Story no Facebook: {offset}/{tamanho}."
                )
            with caminho.open("rb") as arquivo:
                arquivo.seek(offset)
                resposta = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {token}",
                        "offset": str(offset),
                        "file_size": str(tamanho),
                    },
                    data=arquivo,
                    timeout=900,
                )
            if not resposta.ok:
                raise RuntimeError(
                    f"O Facebook falhou no upload do Story ({resposta.status_code}): "
                    f"{resposta.text[:2000]}"
                )
            dados["fase_api"] = "upload_concluido"
            checkpoint(f"Story Facebook parte {parte['ordem']} upload concluído")

        dados["fase_api"] = "finalizacao_pendente_confirmacao"
        checkpoint(f"Story Facebook parte {parte['ordem']} antes de finalizar")
        fim = graph_post(
            f"{page_id}/video_stories",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "access_token": token,
            },
        )
        if not fim.get("success"):
            raise RuntimeError(f"O Facebook não confirmou o Story: {fim}")
        dados["post_id"] = str(fim.get("post_id") or "")
        dados["fase_api"] = "finish_aceito"
        checkpoint(f"Story Facebook parte {parte['ordem']} finish aceito")
        aguardar_video_facebook(str(video_id), token)
        story = aguardar_story_facebook(page_id, str(video_id), token)
        dados["id"] = str(story["post_id"])
        dados["media_id"] = str(video_id)
        dados["fase_api"] = "publicado_confirmado"
        checkpoint(f"Story Facebook parte {parte['ordem']} publicada")
        return str(dados["id"])
    finally:
        if caminho is not None:
            caminho.unlink(missing_ok=True)


def executar_plataforma(
    parte: dict[str, Any],
    plataforma: str,
    funcao: Publicador,
    checkpoint: Checkpoint,
) -> bool:
    dados = parte[plataforma]
    if dados.get("status") == "publicado":
        return True
    dados["ultima_tentativa_em"] = agora_brasilia().isoformat(timespec="seconds")
    dados["tentativas"] = int(dados.get("tentativas", 0)) + 1
    try:
        dados.update(
            {
                "status": "publicado",
                "id": funcao(parte, checkpoint),
                "publicado_em": agora_brasilia().isoformat(timespec="seconds"),
            }
        )
        dados.pop("erro", None)
        return True
    except Exception as erro:
        dados.update({"status": "erro", "erro": str(erro)})
        print(f"ERRO {plataforma}, parte {parte.get('ordem')}: {erro}")
        return False


def main() -> None:
    data = obrigatoria("DATA_PUBLICACAO")
    horario = obrigatoria("HORARIO_PUBLICACAO")
    claim_id = obrigatoria("CLAIM_ID")
    fila = carregar(FILA_STORIES)
    pacote = localizar_story(fila, data, horario)
    if not pacote:
        print(f"Nenhum pacote de Stories pendente em {data} {horario}.")
        return
    if not reivindicacao_valida(pacote, claim_id):
        raise RuntimeError("O pacote de Stories não pertence à reivindicação desta execução.")

    plataforma_alvo = os.getenv("PLATAFORMA_ALVO", "").strip().lower()
    if plataforma_alvo and plataforma_alvo not in PLATAFORMAS:
        raise RuntimeError(f"PLATAFORMA_ALVO inválida: {plataforma_alvo}")
    selecionadas = (plataforma_alvo,) if plataforma_alvo else PLATAFORMAS

    houve_erro = False
    checkpoint = lambda mensagem: salvar_checkpoint(FILA_STORIES, fila, mensagem)
    instagram_disponivel = True
    if "instagram" in selecionadas:
        partes_pendentes_instagram = sum(
            parte.get("instagram", {}).get("status") != "publicado"
            for parte in pacote.get("partes", [])
        )
        try:
            verificar_capacidade_instagram(partes_pendentes_instagram)
        except Exception as erro:
            instagram_disponivel = False
            houve_erro = True
            for parte in pacote.get("partes", []):
                dados = parte.get("instagram", {})
                if dados.get("status") != "publicado":
                    dados["status"] = "erro"
                    dados["erro"] = f"Pré-validação da cota: {erro}"
                    dados["ultima_tentativa_em"] = agora_brasilia().isoformat(timespec="seconds")
            salvar(FILA_STORIES, fila)
            print(f"ERRO Instagram antes do pacote: {erro}")

    for parte in sorted(pacote.get("partes", []), key=lambda item: int(item["ordem"])):
        for plataforma, funcao in (
            ("instagram", publicar_instagram),
            ("facebook", publicar_facebook),
        ):
            if plataforma not in selecionadas:
                continue
            if plataforma == "instagram" and not instagram_disponivel:
                continue
            if not executar_plataforma(parte, plataforma, funcao, checkpoint):
                houve_erro = True
            salvar(FILA_STORIES, fila)
        if any(parte[p].get("status") == "erro" for p in selecionadas):
            break

    if all(
        parte[p].get("status") == "publicado"
        for parte in pacote.get("partes", [])
        for p in PLATAFORMAS
    ):
        pacote.update(
            {
                "status": "concluido",
                "concluido_em": agora_brasilia().isoformat(timespec="seconds"),
            }
        )
    encerrar_claim = os.getenv("ENCERRAR_CLAIM", "").strip().lower() == "true"
    if not plataforma_alvo or encerrar_claim or pacote.get("status") == "concluido":
        pacote.pop("execucao", None)
    salvar(FILA_STORIES, fila)
    if houve_erro:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
