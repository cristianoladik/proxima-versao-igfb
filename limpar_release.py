"""Remove assets somente quando todas as referências nas duas filas concluíram."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any

import requests

from fila_utils import (
    FILA_REELS,
    FILA_STORIES,
    agora_brasilia,
    carregar,
    salvar,
)
from github_release import listar_assets


Referencia = tuple[dict[str, Any], bool]


def referencias_por_asset(
    reels: dict[str, Any], stories: dict[str, Any]
) -> dict[str, list[Referencia]]:
    referencias: dict[str, list[Referencia]] = defaultdict(list)
    for item in reels.get("conteudos", []):
        midia = item["midia"]
        referencias[str(midia["asset"])].append((midia, item.get("status") == "concluido"))
    for pacote in stories.get("pacotes", []):
        concluido = pacote.get("status") == "concluido"
        for parte in pacote.get("partes", []):
            midia = parte["midia"]
            referencias[str(midia["asset"])].append((midia, concluido))
    return dict(referencias)


def assets_elegiveis(
    reels: dict[str, Any], stories: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    resultado: dict[str, list[dict[str, Any]]] = {}
    for nome, referencias in referencias_por_asset(reels, stories).items():
        if not all(concluido for _, concluido in referencias):
            continue
        midias = [midia for midia, _ in referencias]
        if all(midia.get("removido_da_release_em") for midia in midias):
            continue
        metadados = {
            (str(midia.get("sha256", "")).lower(), int(midia.get("tamanho_bytes", 0)))
            for midia in midias
        }
        if len(metadados) != 1:
            raise RuntimeError(f"Referências divergentes para o asset compartilhado {nome}.")
        resultado[nome] = midias
    return resultado


def validar_asset_remoto(
    nome: str, asset: dict[str, Any], amostra: dict[str, Any]
) -> None:
    digest = str(asset.get("digest", "")).removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError(
            f"Recusa de limpeza: a API não forneceu SHA-256 válido para {nome}."
        )
    if digest != str(amostra["sha256"]).lower():
        raise RuntimeError(f"Recusa de limpeza: SHA divergente em {nome}.")
    if int(asset.get("size", -1)) != int(amostra["tamanho_bytes"]):
        raise RuntimeError(f"Recusa de limpeza: tamanho divergente em {nome}.")


def main() -> None:
    repositorio = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag = os.getenv("RELEASE_TAG", "fila-instagram-facebook")
    reels = carregar(FILA_REELS)
    stories = carregar(FILA_STORIES)
    elegiveis = assets_elegiveis(reels, stories)
    if not elegiveis:
        print("Nenhum asset confirmado nas duas redes aguardando limpeza.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    assets = {
        str(asset["name"]): asset
        for asset in listar_assets(repositorio, tag, headers)
    }
    momento = agora_brasilia().isoformat(timespec="seconds")
    for nome, referencias in elegiveis.items():
        asset = assets.get(nome)
        amostra = referencias[0]
        if asset:
            validar_asset_remoto(nome, asset, amostra)
            apagar = requests.delete(
                f"https://api.github.com/repos/{repositorio}/releases/assets/{asset['id']}",
                headers=headers,
                timeout=30,
            )
            if apagar.status_code != 204:
                raise RuntimeError(
                    f"Não foi possível remover {nome}: HTTP {apagar.status_code} "
                    f"{apagar.text[:1000]}"
                )
        for midia in referencias:
            midia["removido_da_release_em"] = momento
    salvar(FILA_REELS, reels)
    salvar(FILA_STORIES, stories)


if __name__ == "__main__":
    main()
