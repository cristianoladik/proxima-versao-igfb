"""Registra no Git uma trava com prazo antes de qualquer chamada à Meta."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fila_utils import (
    FILA_REELS,
    FILA_STORIES,
    agora_brasilia,
    carregar,
    localizar_reel,
    localizar_story,
    salvar,
)

# O conferidor da fila agora só AVISA sobre item ruim, para um vídeo errado lá
# no fim da fila não calar o canal inteiro. Quem barra o item ruim é aqui, na
# hora de publicar, e só o horário dele fica sem publicar (12/09/2026).
from validar_filas import defeito_do_reel, defeito_do_story


def claim_esta_ativo(item: dict[str, Any], agora: datetime) -> bool:
    expiracao = str(item.get("execucao", {}).get("expira_em", ""))
    if not expiracao:
        return False
    try:
        return datetime.fromisoformat(expiracao) > agora
    except ValueError:
        return False


def reivindicar_item(
    item: dict[str, Any] | None,
    claim_id: str,
    agora: datetime,
    minutos: int,
) -> bool:
    if item is None:
        return False
    atual = item.get("execucao", {})
    if atual.get("id") == claim_id:
        return True
    if claim_esta_ativo(item, agora):
        print(f"Item já reivindicado por {atual.get('id', 'outra execução')}.")
        return False
    item["execucao"] = {
        "id": claim_id,
        "reivindicado_em": agora.isoformat(timespec="seconds"),
        "expira_em": (agora + timedelta(minutes=minutos)).isoformat(timespec="seconds"),
    }
    return True


def gravar_output(nome: str, valor: bool) -> None:
    texto = str(valor).lower()
    caminho = os.getenv("GITHUB_OUTPUT")
    if caminho:
        with Path(caminho).open("a", encoding="utf-8") as arquivo:
            arquivo.write(f"{nome}={texto}\n")
    print(f"{nome}={texto}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--horario", required=True)
    parser.add_argument("--escopo", choices=("reel", "story", "ambos"), required=True)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--duracao-minutos", type=int, default=25)
    args = parser.parse_args()
    if args.duracao_minutos < 1:
        raise ValueError("A duração da trava precisa ser positiva.")

    agora = agora_brasilia()
    reels = carregar(FILA_REELS)
    stories = carregar(FILA_STORIES)
    reel = story = False
    if args.escopo in {"reel", "ambos"}:
        item_reel = localizar_reel(reels, args.data, args.horario)
        if item_reel is not None:
            defeito = defeito_do_reel(item_reel, str(item_reel.get("id", "")))
            if defeito:
                # So este horario fica sem publicar; o resto da fila segue.
                raise SystemExit(f"Reel do slot recusado por defeito: {defeito}")
        reel = reivindicar_item(
            item_reel,
            args.claim_id,
            agora,
            args.duracao_minutos,
        )
    if args.escopo in {"story", "ambos"}:
        item_story = localizar_story(stories, args.data, args.horario)
        if item_story is not None:
            defeito = defeito_do_story(item_story, str(item_story.get("id", "")))
            if defeito:
                raise SystemExit(f"Story do slot recusado por defeito: {defeito}")
        story = reivindicar_item(
            item_story,
            args.claim_id,
            agora,
            args.duracao_minutos,
        )
    if reel:
        salvar(FILA_REELS, reels)
    if story:
        salvar(FILA_STORIES, stories)
    gravar_output("reel", reel)
    gravar_output("story", story)


if __name__ == "__main__":
    main()
