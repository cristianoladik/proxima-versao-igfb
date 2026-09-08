# Automação Instagram e Facebook — Próxima Versão

Estrutura técnica baseada no projeto **Como Jesus Cristo faria?**, com filas novas
e sem copiar mídia, IDs, históricos ou credenciais daquele canal.

## Estado atual

O sistema está **preparado, mas bloqueado para publicação**. Ainda faltam a data
inicial do aquecimento, os caminhos finais das pastas, o nome do novo repositório
e as credenciais da Meta. Nenhum cron local foi instalado e nenhum post foi feito.

## Calendário solicitado

- Stories: um vídeo por dia às 09:00, publicado no Instagram e no Facebook.
- Cada vídeo de Story vira partes iguais de no máximo 59 segundos.
- Reels: aquecimento em blocos consecutivos de sete dias.

| Etapa | Reels/dia | Horários provisórios |
|---|---:|---|
| semana 1 | 1 | 05:00 |
| semana 2 | 2 | 05:00, 09:00 |
| semana 3 | 3 | 05:00, 09:00, 13:00 |
| semana 4 | 4 | 05:00, 09:00, 13:00, 17:00 |
| semana 5 em diante | 5 | 05:00, 09:00, 13:00, 17:00, 21:00 |

Essa ordem é configurável. Ela foi adotada provisoriamente por ser a ordem dos
horários informados. A legenda de todos os Reels é
`Siga @palavraquedesperta_br.`.

O limite de 59 segundos é rígido. Por isso, um arquivo com exatamente 120
segundos precisa virar três partes de 40 segundos; duas partes teriam 60 segundos.
Um arquivo de 150 segundos vira três partes de 50 segundos.

## Arquitetura

1. O cortador e o repositor rodam no computador e leem/gravam mídia somente no
   Google Drive.
2. As filas JSON ficam neste repositório técnico.
3. Os MP4 entram temporariamente em uma Release pública, para a Meta conseguir
   baixá-los.
4. Um único workflow atende as cinco janelas. Às 09:00 ele trata Reel e Stories
   separadamente, de modo que a falha de um não bloqueie o outro.
5. Antes de chamar a Meta, o workflow grava no Git uma reivindicação com prazo.
   Uma execução duplicada não consegue publicar o mesmo item.
6. Cada `container_id`/`video_id` e fase é registrada no Git antes da chamada
   irreversível; uma queda retoma o mesmo objeto em vez de publicar outro.
7. Instagram e Facebook têm estados independentes; uma rede já confirmada é
   pulada na retentativa.
8. O asset só sai da Release depois de ambas as redes confirmarem.
9. Durante a reposição local, uma trava versionada impede que o Actions leia uma
   fila intermediária; o SHA remoto é conferido antes de a rotina terminar.

O GitHub Actions oferece cron, mas não garante início no minuto exato e pode
atrasar em períodos de carga. O workflow também aceita `repository_dispatch`
com tipo `publicar_igfb`, para que um único agendador externo confiável envie:

```json
{
  "event_type": "publicar_igfb",
  "client_payload": {
    "data": "2026-09-14",
    "horario": "09:00",
    "escopo": "ambos"
  }
}
```

Não habilite dois agendadores externos para a mesma janela. A trava protege de
duplicidade, mas um único disparador facilita auditoria e pontualidade.

Execute a reposição local fora das janelas. Se a trava de manutenção atravessar
também a retentativa de `:30`, o item permanece pendente e precisa de um disparo
posterior com a data e o horário explícitos.

## Secrets e variável do GitHub

Criar somente estes quatro secrets, todos pertencentes às contas novas:

- `IG_ACCESS_TOKEN`
- `IG_BUSINESS_ID`
- `FB_PAGE_ACCESS_TOKEN`
- `FB_PAGE_ID`

Criar também a variável não sensível `META_GRAPH_VERSION` após validar a versão
vigente da Graph API. A implementação foi validada inicialmente com `v26.0`.
Nunca reutilizar os valores do Projeto Jesus.

Criar ainda `PUBLICACAO_HABILITADA=false`. O job inteiro permanece ignorado
enquanto essa variável não for deliberadamente alterada para `true` na ativação.

Para o mesmo MP4 funcionar nas duas redes, os Reels aceitos usam o perfil comum
conservador: 4 a 60 segundos, MP4 H.264/yuv420p progressivo, 9:16, mínimo
540x960, 23–60 fps e bitrate de vídeo até 25 Mbps. Os Stories aceitos têm de 3 a
59 segundos por parte e passam pela mesma validação técnica.

## Ativação segura

1. Preencher
   `Configuracoes/Instagram e Facebook/configuracao.json` no projeto técnico.
2. Confirmar a data inicial e a ordem dos horários do aquecimento.
3. Criar um repositório público novo e a Release `fila-instagram-facebook`.
4. Configurar os quatro secrets da nova conta e a variável da Graph API.
5. Rodar o diagnóstico, que é somente leitura.
6. Cortar/preparar a fila em simulação e validar SHA-256, tamanhos e durações.
7. Fazer um único teste real, somente após autorização explícita.
8. Só então definir `habilitado=true` e ativar os disparos.

## Comandos locais

Os caminhos ainda estão pendentes; até serem preenchidos, estes comandos falham
de forma segura antes de mover ou enviar mídia.

```powershell
& ".\Robos\Instagram e Facebook\cortar-stories.ps1" -Simular
& ".\Robos\Instagram e Facebook\repor-estoque-igfb.ps1" -Simular
```

O relatório de assets órfãos é sempre somente leitura. Qualquer exclusão fora da
limpeza normal de itens confirmados exige inspeção e confirmação humana.
