"""Normaliza cron, disparo manual ou repository_dispatch em uma janela BRT."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


HORAS_UTC_PARA_BRT = {
    "8": "05:00",
    "12": "09:00",
    "16": "13:00",
    "20": "17:00",
    "0": "21:00",
}
HORARIOS_VALIDOS = {"05:00", "09:00", "13:00", "17:00", "21:00"}
ESCOPOS_VALIDOS = {"auto", "reel", "story", "ambos"}
BRT = timezone(timedelta(hours=-3), name="BRT")
UTC = timezone.utc
ATRASO_MAXIMO_SCHEDULE = timedelta(hours=4)


def janela_agendada(cron: str, agora: datetime) -> tuple[str, str, str]:
    partes = cron.split()
    if len(partes) != 5:
        raise ValueError(f"Cron inesperado: {cron!r}")
    if agora.tzinfo is None:
        raise ValueError("A referência de tempo do schedule precisa conter fuso.")
    try:
        minuto_utc = int(partes[0])
        hora_utc = int(partes[1])
    except ValueError as erro:
        raise ValueError(f"Cron sem hora/minuto fixos: {cron!r}") from erro
    if minuto_utc not in {0, 30} or partes[2:] != ["*", "*", "*"]:
        raise ValueError(f"Cron fora do conjunto autorizado: {cron!r}")
    horario = HORAS_UTC_PARA_BRT.get(partes[1])
    if not horario:
        raise ValueError(f"Hora UTC sem mapeamento: {partes[1]!r}")
    agora_utc = agora.astimezone(UTC)
    ocorrencia = datetime(
        agora_utc.year,
        agora_utc.month,
        agora_utc.day,
        hora_utc,
        minuto_utc,
        tzinfo=UTC,
    )
    if ocorrencia > agora_utc:
        ocorrencia -= timedelta(days=1)
    atraso = agora_utc - ocorrencia
    if atraso > ATRASO_MAXIMO_SCHEDULE:
        raise RuntimeError(
            f"Schedule atrasado {atraso}; limite seguro é {ATRASO_MAXIMO_SCHEDULE}. "
            "Use workflow_dispatch com data explícita após conferir a fila."
        )
    escopo = "ambos" if horario == "09:00" else "reel"
    data_brasilia = ocorrencia.astimezone(BRT).date().isoformat()
    return data_brasilia, horario, escopo


def definir(
    event_name: str,
    cron: str,
    data_manual: str,
    horario_manual: str,
    escopo_manual: str,
    payload: str,
    agora: datetime | None = None,
) -> tuple[str, str, str]:
    referencia = agora or datetime.now(BRT)
    if event_name == "schedule":
        return janela_agendada(cron, referencia)
    if event_name == "repository_dispatch":
        dados = json.loads(payload or "{}")
        data_manual = str(dados.get("data", ""))
        horario_manual = str(dados.get("horario", ""))
        escopo_manual = str(dados.get("escopo", "auto"))
    data_resultado = data_manual or referencia.date().isoformat()
    date.fromisoformat(data_resultado)
    if horario_manual not in HORARIOS_VALIDOS:
        raise ValueError("O horário precisa ser 05:00, 09:00, 13:00, 17:00 ou 21:00.")
    if escopo_manual not in ESCOPOS_VALIDOS:
        raise ValueError("Escopo inválido.")
    escopo = escopo_manual
    if escopo == "auto":
        escopo = "ambos" if horario_manual == "09:00" else "reel"
    if escopo in {"story", "ambos"} and horario_manual != "09:00":
        raise ValueError("Stories só podem ser selecionados para a janela das 09:00.")
    return data_resultado, horario_manual, escopo


def gravar_output(nome: str, valor: str) -> None:
    caminho = os.getenv("GITHUB_OUTPUT")
    if caminho:
        with Path(caminho).open("a", encoding="utf-8") as arquivo:
            arquivo.write(f"{nome}={valor}\n")
    print(f"{nome}={valor}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--cron", default="")
    parser.add_argument("--data", default="")
    parser.add_argument("--horario", default="")
    parser.add_argument("--escopo", default="auto")
    parser.add_argument("--payload", default="")
    args = parser.parse_args()
    data_resultado, horario, escopo = definir(
        args.event_name,
        args.cron,
        args.data,
        args.horario,
        args.escopo,
        args.payload,
    )
    gravar_output("data", data_resultado)
    gravar_output("horario", horario)
    gravar_output("escopo", escopo)


if __name__ == "__main__":
    main()
