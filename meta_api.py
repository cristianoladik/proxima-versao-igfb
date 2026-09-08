"""Cliente mínimo da Graph API usado por Reels e Stories."""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


def obrigatoria(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise RuntimeError(f"Configuração obrigatória ausente: {nome}")
    return valor


def graph_version() -> str:
    valor = os.getenv("META_GRAPH_VERSION", "v26.0").strip()
    if not re.fullmatch(r"v\d+\.\d+", valor):
        raise RuntimeError("META_GRAPH_VERSION precisa ter o formato vNN.N.")
    return valor


def graph_url(caminho: str) -> str:
    return f"https://graph.facebook.com/{graph_version()}/{caminho.lstrip('/')}"


def _erro_http(resposta: requests.Response) -> RuntimeError:
    corpo = resposta.text[:2000]
    return RuntimeError(f"Meta HTTP {resposta.status_code}: {corpo}")


def graph_post(caminho: str, dados: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    resposta = requests.post(graph_url(caminho), data=dados, timeout=timeout)
    if not resposta.ok:
        raise _erro_http(resposta)
    return resposta.json()


def graph_get(caminho: str, parametros: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    resposta = requests.get(graph_url(caminho), params=parametros, timeout=timeout)
    if not resposta.ok:
        raise _erro_http(resposta)
    return resposta.json()


def consultar_container_instagram(container_id: str, token: str) -> dict[str, Any]:
    return graph_get(
        container_id,
        {"fields": "id,status_code,status", "access_token": token},
    )


def aguardar_container_instagram(container_id: str, token: str) -> str:
    for tentativa in range(12):
        status = consultar_container_instagram(container_id, token)
        codigo = str(status.get("status_code", ""))
        print(f"Instagram [{tentativa + 1}/12]: {codigo or 'sem status'}")
        if codigo in {"FINISHED", "PUBLISHED"}:
            return codigo
        if codigo in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"O Instagram não processou o container: {status}")
        time.sleep(30)
    raise TimeoutError("O Instagram demorou mais de seis minutos para processar a mídia.")


def reconciliar_publicacao_instagram(container_id: str, token: str) -> str:
    """Consulta por até cinco minutos depois de uma resposta ambígua de publish."""
    ultimo = ""
    for tentativa in range(6):
        estado = consultar_container_instagram(container_id, token)
        ultimo = str(estado.get("status_code", ""))
        print(f"Instagram reconciliação [{tentativa + 1}/6]: {ultimo or 'sem status'}")
        if ultimo == "PUBLISHED":
            return ultimo
        if ultimo in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"O container não pode ser reconciliado: {estado}")
        if tentativa < 5:
            time.sleep(60)
    return ultimo


def consultar_video_facebook(video_id: str, token: str) -> dict[str, Any]:
    return graph_get(
        video_id,
        {"fields": "status", "access_token": token},
    )


def localizar_story_facebook(
    page_id: str, video_id: str, token: str
) -> dict[str, Any] | None:
    """Reconcilia Story de Página pelo media_id exato retornado no upload."""
    resposta = graph_get(
        f"{page_id}/stories",
        {
            "fields": "media_id,post_id,status,creation_time,media_type",
            "limit": 100,
            "access_token": token,
        },
    )
    for story in resposta.get("data", []):
        if str(story.get("media_id", "")) == str(video_id):
            return story
    return None


def aguardar_story_facebook(
    page_id: str, video_id: str, token: str
) -> dict[str, Any]:
    """Exige o comprovante exato media_id -> post_id na coleção da Página."""
    for tentativa in range(20):
        story = localizar_story_facebook(page_id, video_id, token)
        estado = str((story or {}).get("status", "")).upper()
        print(
            f"Facebook Story [{tentativa + 1}/20]: "
            f"media_id={'encontrado' if story else 'ausente'}, status={estado or '-'}"
        )
        if story and estado in {"PUBLISHED", "ARCHIVED"} and story.get("post_id"):
            return story
        if tentativa < 19:
            time.sleep(15)
    raise TimeoutError(
        f"O Facebook não confirmou o Story {video_id} na coleção da Página em cinco minutos."
    )


def aguardar_video_facebook(video_id: str, token: str) -> dict[str, Any]:
    """Confirma o processamento; success=true no finish é apenas recebimento."""
    for tentativa in range(20):
        resposta = consultar_video_facebook(video_id, token)
        status = resposta.get("status", {}) or {}
        video_status = str(status.get("video_status", "")).lower()
        upload = str((status.get("uploading_phase") or {}).get("status", "")).lower()
        processamento = str((status.get("processing_phase") or {}).get("status", "")).lower()
        fase_publicacao = status.get("publishing_phase") or {}
        publicacao = str(fase_publicacao.get("status", "")).lower()
        publicar_status = str(fase_publicacao.get("publish_status", "")).lower()
        print(
            f"Facebook [{tentativa + 1}/20]: vídeo={video_status or '-'}, "
            f"upload={upload or '-'}, processamento={processamento or '-'}, "
            f"publicação={publicacao or '-'}, publish_status={publicar_status or '-'}"
        )
        valores = {video_status, upload, processamento, publicacao, publicar_status}
        if valores & {"error", "failed", "expired"}:
            raise RuntimeError(f"O Facebook não processou a mídia: {status}")
        if (
            video_status == "published"
            or publicar_status == "published"
        ):
            return resposta
        time.sleep(15)
    raise TimeoutError("O Facebook não confirmou o processamento em cinco minutos.")


def token_pagina_facebook() -> tuple[str, str]:
    token_fornecido = obrigatoria("FB_PAGE_ACCESS_TOKEN")
    page_id = obrigatoria("FB_PAGE_ID")
    resposta = graph_get(
        page_id,
        {"fields": "access_token", "access_token": token_fornecido},
    )
    return str(resposta.get("access_token") or token_fornecido), page_id


def verificar_capacidade_instagram(publicacoes_necessarias: int) -> None:
    if publicacoes_necessarias < 1:
        return
    token = obrigatoria("IG_ACCESS_TOKEN")
    ig_id = obrigatoria("IG_BUSINESS_ID")
    resposta = graph_get(
        f"{ig_id}/content_publishing_limit",
        {
            "fields": "quota_usage,config",
            "access_token": token,
        },
    )
    registros = resposta.get("data", [])
    if not registros:
        raise RuntimeError("A Meta não retornou a cota de publicação do Instagram.")
    registro = registros[0]
    usados = int(registro.get("quota_usage", 0))
    total = int((registro.get("config") or {}).get("quota_total", 0))
    if total < 1:
        raise RuntimeError(f"Cota total do Instagram inválida: {registro}")
    if usados + publicacoes_necessarias > total:
        raise RuntimeError(
            f"Cota insuficiente no Instagram: {usados}/{total} usadas e "
            f"{publicacoes_necessarias} necessárias."
        )
    print(
        f"Cota Instagram: {usados}/{total} usadas; "
        f"{publicacoes_necessarias} publicação(ões) reservadas para esta execução."
    )


def baixar_midia(midia: dict[str, Any]) -> Path:
    url = str(midia.get("url_publica", ""))
    nome = str(midia.get("asset", ""))
    if not url.startswith("https://") or not nome:
        raise RuntimeError("A fila não contém URL HTTPS e nome válidos para a mídia.")
    destino = Path(obrigatoria("MEDIA_CACHE_DIR")) / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    tamanho = 0
    with requests.get(url, stream=True, timeout=(30, 900)) as resposta:
        if not resposta.ok:
            raise RuntimeError(f"Não foi possível baixar {nome}: HTTP {resposta.status_code}")
        with destino.open("wb") as arquivo:
            for bloco in resposta.iter_content(chunk_size=1024 * 1024):
                if bloco:
                    arquivo.write(bloco)
                    digest.update(bloco)
                    tamanho += len(bloco)
    esperado = str(midia.get("sha256", "")).lower()
    if esperado and digest.hexdigest().lower() != esperado:
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 divergente para {nome}.")
    tamanho_esperado = midia.get("tamanho_bytes")
    if tamanho_esperado is not None and tamanho != int(tamanho_esperado):
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"Tamanho divergente para {nome}.")
    return destino
