"""Gerencia a trava distribuída usada durante a reposição local das filas."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


RAIZ = Path(__file__).resolve().parent
ARQUIVO_LOCK = RAIZ / "fila" / "reposicao.lock.json"


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def ler_lock(caminho: Path = ARQUIVO_LOCK) -> dict[str, Any] | None:
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
        expiracao = datetime.fromisoformat(str(dados["expira_em"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as erro:
        raise RuntimeError(
            "A trava de reposição está corrompida; publicação bloqueada para inspeção."
        ) from erro
    if expiracao.tzinfo is None or not dados.get("id"):
        raise RuntimeError("A trava de reposição não contém ID/fuso válidos.")
    return dados


def lock_ativo(dados: dict[str, Any] | None, momento: datetime) -> bool:
    if not dados:
        return False
    return datetime.fromisoformat(str(dados["expira_em"])) > momento


def salvar_lock(lock_id: str, minutos: int, caminho: Path = ARQUIVO_LOCK) -> None:
    if not lock_id or minutos < 1:
        raise ValueError("ID e duração positiva são obrigatórios para a trava.")
    momento = agora_utc()
    existente = ler_lock(caminho)
    if lock_ativo(existente, momento) and existente.get("id") != lock_id:
        raise RuntimeError(
            f"Outra reposição mantém a trava até {existente['expira_em']}."
        )
    dados = {
        "versao_schema": 1,
        "id": lock_id,
        "adquirido_em": momento.isoformat(timespec="seconds"),
        "expira_em": (momento + timedelta(minutes=minutos)).isoformat(timespec="seconds"),
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporario.replace(caminho)


def liberar_lock(lock_id: str, caminho: Path = ARQUIVO_LOCK) -> None:
    dados = ler_lock(caminho)
    if not dados:
        return
    if dados.get("id") != lock_id:
        raise RuntimeError("A reposição recusou remover a trava pertencente a outra execução.")
    caminho.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="comando", required=True)
    adquirir = sub.add_parser("adquirir")
    adquirir.add_argument("--id", required=True)
    adquirir.add_argument("--duracao-minutos", type=int, default=360)
    liberar = sub.add_parser("liberar")
    liberar.add_argument("--id", required=True)
    sub.add_parser("verificar")
    args = parser.parse_args()

    if args.comando == "adquirir":
        salvar_lock(args.id, args.duracao_minutos)
        print(f"Trava de reposição preparada: {args.id}.")
        return
    if args.comando == "liberar":
        liberar_lock(args.id)
        print(f"Trava de reposição liberada: {args.id}.")
        return

    dados = ler_lock()
    if lock_ativo(dados, agora_utc()):
        raise SystemExit(
            f"Publicação adiada: reposição {dados['id']} ativa até {dados['expira_em']}."
        )
    print("Nenhuma reposição ativa; publicação liberada.")


if __name__ == "__main__":
    main()
