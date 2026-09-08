"""Confere IDs e acesso de leitura da Meta sem criar publicação."""

from __future__ import annotations

from meta_api import graph_get, obrigatoria, token_pagina_facebook


def main() -> None:
    ig_id = obrigatoria("IG_BUSINESS_ID")
    ig_token = obrigatoria("IG_ACCESS_TOKEN")
    instagram = graph_get(
        ig_id,
        {"fields": "id,username,media_count,account_type", "access_token": ig_token},
    )
    page_token, page_id = token_pagina_facebook()
    pagina = graph_get(
        page_id,
        {"fields": "id,name,instagram_business_account", "access_token": page_token},
    )
    print(
        "Instagram confirmado: "
        f"@{instagram.get('username', 'desconhecido')} (ID {instagram.get('id', 'ausente')})."
    )
    print(
        "Página do Facebook confirmada: "
        f"{pagina.get('name', 'desconhecida')} (ID {pagina.get('id', 'ausente')})."
    )
    vinculo = pagina.get("instagram_business_account", {}).get("id")
    if str(vinculo or "") != str(ig_id):
        raise RuntimeError(
            f"A Página aponta para o Instagram {vinculo or 'ausente'}, "
            f"mas IG_BUSINESS_ID é {ig_id}."
        )
    if str(instagram.get("account_type", "")).upper() != "BUSINESS":
        raise RuntimeError(
            "A conta do Instagram precisa ser Business para este fluxo de Stories; "
            f"tipo retornado: {instagram.get('account_type', 'ausente')}."
        )
    print("Diagnóstico somente leitura concluído; nenhuma mídia foi criada ou publicada.")


if __name__ == "__main__":
    main()
