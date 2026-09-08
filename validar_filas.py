"""Validação offline dos esquemas, horários, IDs e mídias das duas filas."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fila_utils import FILA_REELS, FILA_STORIES, carregar


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HORARIOS_REELS = {"05:00", "09:00", "13:00", "17:00", "21:00"}
STATUS_ITEM = {"pendente", "concluido"}
STATUS_PLATAFORMA = {"pendente", "erro", "publicado"}
FASES_INSTAGRAM = {
    "container_criado",
    "container_pronto",
    "publicacao_pendente_confirmacao",
    "publicado_confirmado",
}
FASES_FACEBOOK = {
    "upload_iniciado",
    "upload_concluido",
    "finalizacao_pendente_confirmacao",
    "finish_aceito",
    "publicado_confirmado",
}


def validar_data_iso(valor: Any, contexto: str) -> str:
    texto = str(valor or "")
    try:
        date.fromisoformat(texto)
    except ValueError as erro:
        raise RuntimeError(f"Data inválida em {contexto}: {texto!r}") from erro
    return texto


def validar_origem(origem: dict[str, Any], contexto: str) -> None:
    if not origem.get("arquivo"):
        raise RuntimeError(f"Arquivo de origem ausente em {contexto}.")
    if not SHA256_RE.fullmatch(str(origem.get("sha256", "")).lower()):
        raise RuntimeError(f"SHA-256 da origem inválido em {contexto}.")


def validar_execucao(item: dict[str, Any], contexto: str) -> None:
    execucao = item.get("execucao")
    if not execucao:
        return
    if not execucao.get("id"):
        raise RuntimeError(f"ID da reivindicação ausente em {contexto}.")
    for campo in ("reivindicado_em", "expira_em"):
        try:
            momento = datetime.fromisoformat(str(execucao.get(campo, "")))
        except ValueError as erro:
            raise RuntimeError(f"{campo} inválido em {contexto}.") from erro
        if momento.tzinfo is None:
            raise RuntimeError(f"{campo} precisa conter fuso em {contexto}.")


def validar_plataforma(
    dados: dict[str, Any], contexto: str, exigir_legenda: bool, plataforma: str
) -> None:
    status = str(dados.get("status", ""))
    if status not in STATUS_PLATAFORMA:
        raise RuntimeError(f"Status de plataforma inválido em {contexto}: {status!r}")
    if exigir_legenda and not dados.get("legenda"):
        raise RuntimeError(f"Legenda ausente em {contexto}.")
    if status == "publicado" and not dados.get("id"):
        raise RuntimeError(f"Publicação sem ID em {contexto}.")
    if status == "erro" and not dados.get("erro"):
        raise RuntimeError(f"Estado de erro sem mensagem em {contexto}.")
    if "upload_url" in dados:
        raise RuntimeError(f"URL transitória de upload não pode ser gravada em {contexto}.")
    fase = str(dados.get("fase_api", ""))
    if fase:
        permitidas = FASES_INSTAGRAM if plataforma == "instagram" else FASES_FACEBOOK
        if fase not in permitidas:
            raise RuntimeError(f"Fase da API inválida em {contexto}: {fase!r}")
        identificador_externo = "container_id" if plataforma == "instagram" else "video_id"
        if not dados.get(identificador_externo):
            raise RuntimeError(
                f"{identificador_externo} ausente para a fase {fase} em {contexto}."
            )
        if fase == "publicado_confirmado" and not dados.get("id"):
            raise RuntimeError(f"Fase publicada sem ID final em {contexto}.")


def validar_midia(midia: dict[str, Any], contexto: str, tipo: str) -> None:
    digest = str(midia.get("sha256", "")).lower()
    if not SHA256_RE.fullmatch(digest):
        raise RuntimeError(f"SHA-256 inválido em {contexto}.")
    tamanho = int(midia.get("tamanho_bytes", 0))
    tamanho_maximo = 300_000_000 if tipo == "reel" else 100_000_000
    if tamanho <= 0 or tamanho > tamanho_maximo:
        raise RuntimeError(f"Tamanho inválido em {contexto}.")
    if not str(midia.get("url_publica", "")).startswith("https://github.com/"):
        raise RuntimeError(f"URL pública inválida em {contexto}.")
    if not midia.get("asset"):
        raise RuntimeError(f"Nome de asset ausente em {contexto}.")
    asset = str(midia["asset"])
    if "/" in asset or "\\" in asset or not asset.lower().endswith(".mp4"):
        raise RuntimeError(f"Nome de asset inseguro em {contexto}.")
    segundos = float(midia.get("duracao_segundos", 0))
    minimo = 4.0 if tipo == "reel" else 3.0
    limite = 60.0 if tipo == "reel" else 59.0
    if segundos < minimo or segundos > limite:
        raise RuntimeError(
            f"Duração fora do intervalo {minimo:g}–{limite:g}s em {contexto}."
        )
    largura = int(midia.get("largura", 0))
    altura = int(midia.get("altura", 0))
    if (
        largura < 540
        or largura > 1920
        or altura < 960
        or abs((largura / altura) - (9 / 16)) > 0.01
    ):
        raise RuntimeError(f"Resolução/proporção incompatível em {contexto}.")
    fps = float(midia.get("fps", 0))
    if fps < 23.0 or fps > 60.0:
        raise RuntimeError(f"FPS incompatível em {contexto}.")
    bitrate = int(midia.get("bitrate_video_bps", 0))
    if bitrate <= 0 or bitrate > 25_000_000:
        raise RuntimeError(f"Bitrate incompatível em {contexto}.")
    if midia.get("codec_video") != "h264" or midia.get("formato_pixel") != "yuv420p":
        raise RuntimeError(f"Codec ou formato de pixel incompatível em {contexto}.")


def validar_reels(fila: dict[str, Any]) -> int:
    if fila.get("versao_schema") != 1 or fila.get("canal") != "instagram-facebook-reels":
        raise RuntimeError("Cabeçalho da fila de Reels inválido.")
    ids: set[str] = set()
    janelas: set[tuple[str, str]] = set()
    for item in fila.get("conteudos", []):
        identificador = str(item.get("id", ""))
        janela = (validar_data_iso(item.get("data"), identificador), str(item.get("horario", "")))
        if not identificador or identificador in ids:
            raise RuntimeError(f"ID de Reel ausente ou repetido: {identificador!r}")
        if janela in janelas or janela[1] not in HORARIOS_REELS:
            raise RuntimeError(f"Janela de Reel inválida ou repetida: {janela}")
        ids.add(identificador)
        janelas.add(janela)
        if item.get("status") not in STATUS_ITEM:
            raise RuntimeError(f"Status de Reel inválido em {identificador}.")
        validar_origem(item.get("origem", {}), identificador)
        validar_execucao(item, identificador)
        validar_midia(item.get("midia", {}), identificador, "reel")
        for plataforma in ("instagram", "facebook"):
            validar_plataforma(
                item.get(plataforma, {}),
                f"{identificador}/{plataforma}",
                exigir_legenda=True,
                plataforma=plataforma,
            )
        if item.get("status") == "concluido" and not all(
            item[p].get("status") == "publicado" for p in ("instagram", "facebook")
        ):
            raise RuntimeError(f"Reel concluído sem as duas confirmações: {identificador}")
    return len(ids)


def validar_stories(fila: dict[str, Any]) -> tuple[int, int]:
    if fila.get("versao_schema") != 1 or fila.get("canal") != "instagram-facebook-stories":
        raise RuntimeError("Cabeçalho da fila de Stories inválido.")
    ids: set[str] = set()
    datas: set[str] = set()
    total_partes = 0
    for pacote in fila.get("pacotes", []):
        identificador = str(pacote.get("id", ""))
        data = validar_data_iso(pacote.get("data"), identificador)
        if not identificador or identificador in ids:
            raise RuntimeError(f"ID de Story ausente ou repetido: {identificador!r}")
        if data in datas or pacote.get("horario", "09:00") != "09:00":
            raise RuntimeError(f"Data/horário de Story inválido ou repetido: {data}")
        ids.add(identificador)
        datas.add(data)
        if pacote.get("status") not in STATUS_ITEM:
            raise RuntimeError(f"Status de Story inválido em {identificador}.")
        validar_origem(pacote.get("origem", {}), identificador)
        validar_execucao(pacote, identificador)
        partes = pacote.get("partes", [])
        if not partes:
            raise RuntimeError(f"Pacote de Story sem partes: {identificador}")
        if len(partes) > 95:
            raise RuntimeError(f"Pacote de Story excede 95 partes: {identificador}")
        ordens = [int(parte.get("ordem", 0)) for parte in partes]
        if ordens != list(range(1, len(partes) + 1)):
            raise RuntimeError(f"Ordem descontínua no pacote {identificador}.")
        for parte in partes:
            contexto = f"{identificador}/parte-{parte['ordem']}"
            validar_midia(parte.get("midia", {}), contexto, "story")
            segundos = float(parte["midia"].get("duracao_segundos", 0))
            if segundos < 3.0 or segundos > 59.0:
                raise RuntimeError(f"Parte de Story fora do intervalo 3–59 segundos: {contexto}")
            for plataforma in ("instagram", "facebook"):
                validar_plataforma(
                    parte.get(plataforma, {}),
                    f"{contexto}/{plataforma}",
                    exigir_legenda=False,
                    plataforma=plataforma,
                )
        if pacote.get("status") == "concluido" and not all(
            parte[p].get("status") == "publicado"
            for parte in partes
            for p in ("instagram", "facebook")
        ):
            raise RuntimeError(f"Story concluído sem todas as confirmações: {identificador}")
        total_partes += len(partes)
    return len(ids), total_partes


def main() -> None:
    reels = validar_reels(carregar(FILA_REELS))
    stories, partes = validar_stories(carregar(FILA_STORIES))
    print(f"OK: {reels} Reels, {stories} pacotes de Stories e {partes} partes válidas.")


if __name__ == "__main__":
    main()
