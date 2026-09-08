"""Relata assets órfãos da Release sem apagar ou alterar nada."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from fila_utils import FILA_REELS, FILA_STORIES, carregar
from github_release import listar_assets


def nomes_referenciados(reels: dict[str, Any], stories: dict[str, Any]) -> set[str]:
    nomes = {
        str(item["midia"]["asset"])
        for item in reels.get("conteudos", [])
        if not item["midia"].get("removido_da_release_em")
    }
    for pacote in stories.get("pacotes", []):
        nomes.update(
            str(parte["midia"]["asset"])
            for parte in pacote.get("partes", [])
            if not parte["midia"].get("removido_da_release_em")
        )
    return nomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relatorio", type=Path)
    args = parser.parse_args()
    repositorio = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag = os.getenv("RELEASE_TAG", "fila-instagram-facebook")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    assets = listar_assets(repositorio, tag, headers)
    referencias = nomes_referenciados(carregar(FILA_REELS), carregar(FILA_STORIES))
    orfaos = [
        {"nome": asset["name"], "tamanho_bytes": int(asset.get("size", 0))}
        for asset in assets
        if str(asset["name"]) not in referencias
    ]
    relatorio = {
        "release": tag,
        "assets_total": len(assets),
        "assets_referenciados": len(assets) - len(orfaos),
        "assets_orfaos": len(orfaos),
        "bytes_orfaos": sum(item["tamanho_bytes"] for item in orfaos),
        "orfaos": orfaos,
        "observacao": "Relatório somente leitura; nenhuma exclusão foi executada.",
    }
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n"
    if args.relatorio:
        args.relatorio.write_text(texto, encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    main()
