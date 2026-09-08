"""Leitura paginada de Releases pela API oficial do GitHub."""

from __future__ import annotations

from typing import Any

import requests


def listar_assets(
    repositorio: str,
    tag: str,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    release = requests.get(
        f"https://api.github.com/repos/{repositorio}/releases/tags/{tag}",
        headers=headers,
        timeout=30,
    )
    release.raise_for_status()
    release_id = release.json().get("id")
    if not release_id:
        raise RuntimeError(f"A Release {tag} não retornou ID.")
    resultado: list[dict[str, Any]] = []
    pagina = 1
    while True:
        resposta = requests.get(
            f"https://api.github.com/repos/{repositorio}/releases/{release_id}/assets",
            headers=headers,
            params={"per_page": 100, "page": pagina},
            timeout=30,
        )
        resposta.raise_for_status()
        lote = resposta.json()
        resultado.extend(lote)
        if len(lote) < 100:
            return resultado
        pagina += 1
