"""Utilitários pequenos e compartilhados pelas filas do publicador."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
FILA_REELS = ROOT / "fila" / "fila-reels.json"
FILA_STORIES = ROOT / "fila" / "fila-stories.json"
FUSO = timezone(timedelta(hours=-3), name="BRT")
PLATAFORMAS = ("instagram", "facebook")


def agora_brasilia() -> datetime:
    return datetime.now(FUSO)


def carregar(caminho: Path) -> dict[str, Any]:
    return json.loads(caminho.read_text(encoding="utf-8-sig"))


def salvar(caminho: Path, dados: dict[str, Any]) -> None:
    temporario = caminho.with_name(f".{caminho.name}.{uuid.uuid4().hex}.tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.loads(temporario.read_text(encoding="utf-8"))
    temporario.replace(caminho)


def checkpoint(caminho: Path, dados: dict[str, Any], mensagem: str) -> None:
    """Persiste estado local e, no Actions, antes de uma chamada irreversível à Meta."""
    salvar(caminho, dados)
    if os.getenv("CHECKPOINT_GIT", "").strip().lower() != "true":
        return
    try:
        relativo = caminho.resolve().relative_to(ROOT.resolve())
    except ValueError as erro:
        raise RuntimeError("O checkpoint recusou um arquivo fora do repositório.") from erro
    subprocess.run(
        ("git", "-C", str(ROOT), "add", relativo.as_posix()),
        check=True,
    )
    diferenca = subprocess.run(
        ("git", "-C", str(ROOT), "diff", "--staged", "--quiet"),
        check=False,
    )
    if diferenca.returncode == 0:
        return
    if diferenca.returncode != 1:
        raise RuntimeError("Não foi possível verificar o checkpoint no Git.")
    subprocess.run(
        ("git", "-C", str(ROOT), "commit", "-m", f"chore: checkpoint {mensagem}"),
        check=True,
    )
    # O grupo de concorrência garante um publicador por vez. Se outro processo
    # mudou a fila, é mais seguro interromper antes da próxima chamada à Meta.
    subprocess.run(("git", "-C", str(ROOT), "push"), check=True)


STATUS_FINAIS = {"concluido", "pulado"}
# Depois de tantas tentativas falhas numa rede, o item sai da vez e o próximo
# pendente da fila assume o horário. Regra do Cristiano em 15/09/2026: quando
# há recusa, tentar os próximos vídeos da fila até conseguir.
MAX_TENTATIVAS_ANTES_DE_PULAR = 3
MAX_SUBSTITUICOES_POR_RODADA = 5


def esgotou_tentativas(blocos: list[dict[str, Any]], plataformas: tuple[str, ...]) -> bool:
    """True se alguma rede está em erro com o máximo de tentativas em algum bloco."""

    for bloco in blocos:
        for plataforma in plataformas:
            dados = bloco.get(plataforma, {})
            if dados.get("status") == "erro" and int(dados.get("tentativas", 0)) >= MAX_TENTATIVAS_ANTES_DE_PULAR:
                return True
    return False


def pular_e_puxar_proximo(
    fila: dict[str, Any],
    chave_lista: str,
    item: dict[str, Any],
    data: str,
    horario: str,
) -> dict[str, Any] | None:
    """Marca o item como pulado e traz o próximo pendente para o mesmo horário.

    O item pulado guarda o erro para diagnóstico. O que assume a vaga registra
    de onde veio; a reivindicação desta execução passa para ele.
    """

    item["status"] = "pulado"
    item["pulado_em"] = agora_brasilia().isoformat(timespec="seconds")
    execucao = item.pop("execucao", None)
    candidatos = sorted(
        (
            outro
            for outro in fila.get(chave_lista, [])
            if outro is not item
            and outro.get("status") == "pendente"
            and (str(outro.get("data", "")), str(outro.get("horario", "09:00"))) > (data, horario)
        ),
        key=lambda outro: (str(outro.get("data", "")), str(outro.get("horario", "09:00"))),
    )
    if not candidatos:
        print(f"PULADO {item.get('id')}: sem próximo pendente na fila para assumir {data} {horario}.")
        return None
    proximo = candidatos[0]
    proximo["reagendado_de"] = f"{proximo.get('data')} {proximo.get('horario', '09:00')}"
    proximo["data"] = data
    proximo["horario"] = horario
    if execucao:
        proximo["execucao"] = execucao
    print(f"PULADO {item.get('id')} após {MAX_TENTATIVAS_ANTES_DE_PULAR} tentativas; {proximo.get('id')} assume {data} {horario}.")
    return proximo


def localizar_reel(fila: dict[str, Any], data: str, horario: str) -> dict[str, Any] | None:
    encontrados = [
        item
        for item in fila.get("conteudos", [])
        if item.get("data") == data
        and item.get("horario") == horario
        and item.get("status") not in STATUS_FINAIS
    ]
    if len(encontrados) > 1:
        raise RuntimeError(f"Mais de um Reel encontrado em {data} {horario}.")
    return encontrados[0] if encontrados else None


def localizar_story(fila: dict[str, Any], data: str, horario: str) -> dict[str, Any] | None:
    encontrados = [
        item
        for item in fila.get("pacotes", [])
        if item.get("data") == data
        and item.get("horario", "09:00") == horario
        and item.get("status") not in STATUS_FINAIS
    ]
    if len(encontrados) > 1:
        raise RuntimeError(f"Mais de um pacote de Stories encontrado em {data} {horario}.")
    return encontrados[0] if encontrados else None


def reivindicacao_valida(item: dict[str, Any], claim_id: str) -> bool:
    return bool(claim_id) and item.get("execucao", {}).get("id") == claim_id
