"""Publica exatamente um Reel reivindicado no Instagram e no Facebook."""

from __future__ import annotations

import os
from typing import Any, Callable

import requests

from fila_utils import (
    FILA_REELS,
    PLATAFORMAS,
    agora_brasilia,
    carregar,
    checkpoint as salvar_checkpoint,
    localizar_reel,
    reivindicacao_valida,
    salvar,
)
from meta_api import (
    aguardar_container_instagram,
    aguardar_video_facebook,
    baixar_midia,
    consultar_video_facebook,
    graph_post,
    obrigatoria,
    reconciliar_publicacao_instagram,
    token_pagina_facebook,
    verificar_capacidade_instagram,
)


Checkpoint = Callable[[str], None]
Publicador = Callable[[dict[str, Any], Checkpoint], str]


def publicar_instagram(item: dict[str, Any], checkpoint: Checkpoint) -> str:
    dados = item["instagram"]
    if dados.get("id"):
        return str(dados["id"])
    token = obrigatoria("IG_ACCESS_TOKEN")
    ig_id = obrigatoria("IG_BUSINESS_ID")
    midia = item["midia"]
    container_id = dados.get("container_id")
    fase = str(dados.get("fase_api", ""))
    if container_id and fase == "publicacao_pendente_confirmacao":
        estado = reconciliar_publicacao_instagram(str(container_id), token)
        if estado == "PUBLISHED":
            dados["id"] = str(container_id)
            dados["id_tipo"] = "container_id_publicacao_reconciliada"
            dados["fase_api"] = "publicado_confirmado"
            checkpoint(f"Reel Instagram reconciliado {item['id']}")
            return str(container_id)
        # FINISHED após a janela de reconciliação permite repetir somente o
        # media_publish do mesmo creation_id; nunca se cria outro container.
        if estado != "FINISHED":
            raise RuntimeError(
                f"Estado inconclusivo do container Instagram {container_id}: {estado!r}."
            )
    if container_id and fase == "publicado_confirmado":
        raise RuntimeError("Container marcado como publicado, mas sem ID final na fila.")
    if not container_id:
        container = graph_post(
            f"{ig_id}/media",
            {
                "media_type": "REELS",
                "video_url": midia["url_publica"],
                "caption": dados["legenda"],
                "share_to_feed": "true",
                "access_token": token,
            },
        )
        container_id = container.get("id")
        if not container_id:
            raise RuntimeError(f"Container do Instagram sem ID: {container}")
        dados["container_id"] = str(container_id)
        dados["fase_api"] = "container_criado"
        checkpoint(f"Reel Instagram container {item['id']}")

    estado = aguardar_container_instagram(str(container_id), token)
    if estado == "PUBLISHED":
        dados["id"] = str(container_id)
        dados["id_tipo"] = "container_id_publicacao_reconciliada"
        dados["fase_api"] = "publicado_confirmado"
        checkpoint(f"Reel Instagram reconciliado {item['id']}")
        return str(container_id)
    dados["fase_api"] = "container_pronto"
    checkpoint(f"Reel Instagram pronto {item['id']}")
    verificar_capacidade_instagram(1)
    # O checkpoint vem antes da chamada irreversível. Se a resposta se perder,
    # a retomada bloqueia para reconciliação em vez de criar uma duplicata.
    dados["fase_api"] = "publicacao_pendente_confirmacao"
    checkpoint(f"Reel Instagram antes de publicar {item['id']}")
    publicado = graph_post(
        f"{ig_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
    )
    if not publicado.get("id"):
        raise RuntimeError(f"O Instagram não retornou o Reel publicado: {publicado}")
    dados["id"] = str(publicado["id"])
    dados["fase_api"] = "publicado_confirmado"
    checkpoint(f"Reel Instagram publicado {item['id']}")
    return str(dados["id"])


def publicar_facebook(item: dict[str, Any], checkpoint: Checkpoint) -> str:
    dados = item["facebook"]
    if dados.get("id"):
        return str(dados["id"])
    token, page_id = token_pagina_facebook()
    video_id = dados.get("video_id")
    fase = str(dados.get("fase_api", ""))
    if video_id and fase in {"finalizacao_pendente_confirmacao", "finish_aceito"}:
        try:
            aguardar_video_facebook(str(video_id), token)
        except TimeoutError:
            if fase == "finish_aceito":
                raise
            # A consulta não achou publicação em cinco minutos. É permitido
            # repetir finish no mesmo video_id, sem abrir outra sessão.
            dados["fase_api"] = "upload_concluido"
            checkpoint(f"Reel Facebook finish reconciliado {item['id']}")
            fase = "upload_concluido"
        else:
            dados["id"] = str(video_id)
            dados["fase_api"] = "publicado_confirmado"
            checkpoint(f"Reel Facebook reconciliado {item['id']}")
            return str(video_id)
    if video_id and fase == "publicado_confirmado":
        dados["id"] = str(video_id)
        checkpoint(f"Reel Facebook ID restaurado {item['id']}")
        return str(video_id)
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
            checkpoint(f"Reel Facebook upload reconciliado {item['id']}")
            fase = "upload_concluido"
        else:
            # start/upload não publica nada sem finish. Como a upload_url pode
            # ser transitória e não deve ir para um repositório público, uma
            # sessão comprovadamente incompleta é abandonada antes de um start novo.
            dados.setdefault("uploads_abandonados", []).append(str(video_id))
            dados.pop("video_id", None)
            dados.pop("fase_api", None)
            checkpoint(f"Reel Facebook upload incompleto abandonado {item['id']}")
            video_id = None
            fase = ""
    if video_id and fase not in {"upload_concluido"}:
        raise RuntimeError(
            f"Estado de retomada desconhecido do Reel no Facebook: {fase!r}."
        )

    caminho = None
    try:
        if not video_id:
            caminho = baixar_midia(item["midia"])
            inicio = graph_post(
                f"{page_id}/video_reels",
                {"upload_phase": "start", "access_token": token},
            )
            video_id = inicio.get("video_id")
            upload_url = inicio.get("upload_url")
            if not video_id or not upload_url:
                raise RuntimeError(f"O Facebook não iniciou o upload do Reel: {inicio}")
            dados["video_id"] = str(video_id)
            dados["fase_api"] = "upload_iniciado"
            checkpoint(f"Reel Facebook upload iniciado {item['id']}")
            offset = 0
        else:
            offset = None

        if offset is not None:
            tamanho = caminho.stat().st_size
            if offset < 0 or offset > tamanho:
                raise RuntimeError(
                    f"Offset remoto inválido para o Reel no Facebook: {offset}/{tamanho}."
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
                    f"O Facebook falhou no upload ({resposta.status_code}): "
                    f"{resposta.text[:2000]}"
                )
            dados["fase_api"] = "upload_concluido"
            checkpoint(f"Reel Facebook upload concluído {item['id']}")

        dados["fase_api"] = "finalizacao_pendente_confirmacao"
        checkpoint(f"Reel Facebook antes de finalizar {item['id']}")
        fim = graph_post(
            f"{page_id}/video_reels",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": dados["legenda"],
                "access_token": token,
            },
        )
        if not fim.get("success"):
            raise RuntimeError(f"O Facebook não confirmou o Reel: {fim}")
        dados["fase_api"] = "finish_aceito"
        checkpoint(f"Reel Facebook finish aceito {item['id']}")
        aguardar_video_facebook(str(video_id), token)
        dados["id"] = str(video_id)
        dados["fase_api"] = "publicado_confirmado"
        checkpoint(f"Reel Facebook publicado {item['id']}")
        return str(video_id)
    finally:
        if caminho is not None:
            caminho.unlink(missing_ok=True)


def executar_plataforma(
    item: dict[str, Any],
    plataforma: str,
    funcao: Publicador,
    checkpoint: Checkpoint,
) -> bool:
    dados = item[plataforma]
    if dados.get("status") == "publicado":
        return True
    agora = agora_brasilia()
    dados["ultima_tentativa_em"] = agora.isoformat(timespec="seconds")
    dados["tentativas"] = int(dados.get("tentativas", 0)) + 1
    try:
        identificador = funcao(item, checkpoint)
        dados.update(
            {
                "status": "publicado",
                "id": identificador,
                "publicado_em": agora_brasilia().isoformat(timespec="seconds"),
            }
        )
        dados.pop("erro", None)
        return True
    except Exception as erro:
        dados.update({"status": "erro", "erro": str(erro)})
        print(f"ERRO {plataforma}: {erro}")
        return False


def main() -> None:
    data = obrigatoria("DATA_PUBLICACAO")
    horario = obrigatoria("HORARIO_PUBLICACAO")
    claim_id = obrigatoria("CLAIM_ID")
    fila = carregar(FILA_REELS)
    item = localizar_reel(fila, data, horario)
    if not item:
        print(f"Nenhum Reel pendente em {data} {horario}.")
        return
    if not reivindicacao_valida(item, claim_id):
        raise RuntimeError("O Reel não pertence à reivindicação desta execução.")

    plataforma_alvo = os.getenv("PLATAFORMA_ALVO", "").strip().lower()
    if plataforma_alvo and plataforma_alvo not in PLATAFORMAS:
        raise RuntimeError(f"PLATAFORMA_ALVO inválida: {plataforma_alvo}")
    selecionadas = (plataforma_alvo,) if plataforma_alvo else PLATAFORMAS

    resultados: list[bool] = []
    checkpoint = lambda mensagem: salvar_checkpoint(FILA_REELS, fila, mensagem)
    for plataforma, funcao in (
        ("instagram", publicar_instagram),
        ("facebook", publicar_facebook),
    ):
        if plataforma not in selecionadas:
            continue
        resultados.append(executar_plataforma(item, plataforma, funcao, checkpoint))
        salvar(FILA_REELS, fila)

    if all(item[p].get("status") == "publicado" for p in PLATAFORMAS):
        item.update(
            {
                "status": "concluido",
                "concluido_em": agora_brasilia().isoformat(timespec="seconds"),
            }
        )
    encerrar_claim = os.getenv("ENCERRAR_CLAIM", "").strip().lower() == "true"
    if not plataforma_alvo or encerrar_claim or item.get("status") == "concluido":
        item.pop("execucao", None)
    salvar(FILA_REELS, fila)
    if not all(resultados):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
