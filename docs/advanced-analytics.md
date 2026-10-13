# Estatísticas avançadas, contadores e cargos por atividade

## Escopo

A implementação adiciona à arquitetura existente do BN Bot estatísticas agregadas e históricas, contadores em canais de voz/palco, consulta de atividade por canal e membro, filtros por servidor e regras de cargos baseadas em atividade. A interface principal fica em **Dashboard → Estatísticas**. Os recursos reutilizam `MemberActivity`, `ChannelActivity`, `MessageLog`, as configurações de guilda, a API autenticada e o worker existente.

Não foram adicionados os comandos `/instagram` ou `/tiktok`, serviços relacionados nem dependências exclusivas desses recursos.

## O que é coletado

- Mensagens aceitas pelos filtros são agregadas por membro, canal e hora UTC. O log guarda metadados mínimos (ID, servidor, canal, usuário, tamanho do conteúdo e horário original); não armazena o texto da mensagem.
- Sessões de voz aceitas pelos filtros são divididas em segmentos por hora e atribuídas ao canal da sessão. Ao reiniciar o bot, uma sessão ainda ativa é retomada a partir do momento da restauração, sem contabilizar a indisponibilidade como tempo de voz.
- Entradas e saídas são agregadas em `guild_activity`.
- A quantidade de membros é registrada como snapshot horário, sem somar snapshots entre si.
- A retenção remove dados históricos fora da janela configurada. O limite configurável fica entre 30 e 3650 dias (padrão: 365 dias).

**Limite histórico:** o sistema não inventa dados que não existiam. O histórico confiável começa na primeira coleta disponível. Snapshots de membros, por exemplo, só permitem acompanhar a evolução desde que o worker começou a registrá-los. Filtros novos também são prospectivos; agregações anteriores não são recalculadas automaticamente.

## Estatísticas e períodos

A página exibe os valores disponíveis para 24 horas, 7, 30 e 90 dias: mensagens, segundos em voz, membros ativos, entradas/saídas, canais e membros mais ativos, distribuição horária e evolução do número de membros. A comparação usa um período anterior de igual duração. Quando o período anterior tem valor zero, a variação percentual é `null`/indisponível, não uma porcentagem inventada.

O detalhamento de canal mostra mensagens, tempo em voz, série temporal e membros únicos identificados em logs de mensagens. Como a sessão OAuth atual não contém as permissões específicas de cada canal, o ranking e o detalhe por canal ficam restritos ao proprietário do servidor ou ao administrador do BN Bot, evitando expor métricas de canais privados a gestores sem acesso confirmado. As estatísticas agregadas do servidor continuam visíveis aos gestores autorizados. O perfil estatístico individual mostra atividade histórica disponível, atividade recente, dias ativos, tempo em voz acumulado e data de entrada. As estatísticas individuais podem ser restringidas para administradores/gerentes pela configuração `member_statistics_for_managers`.

## Filtros por servidor

O endpoint de configurações suporta:

- `excluded_channel_ids`, `excluded_category_ids`, `excluded_role_ids`;
- `exclude_commands` e `exclude_bots`;
- `track_voice`;
- `retention_days` (30-3650);
- `member_statistics_for_managers`.

Listas de IDs aceitam no máximo 200 itens por lista e IDs positivos sem duplicação. Por padrão, bots e comandos que mencionam o bot são excluídos das estatísticas. O filtro por conteúdo de comando detecta menções ao bot, não todos os comandos de aplicação slash, porque esses comandos nem sempre geram uma mensagem comum que possa ser observada pelo bot.

Desativar o rastreamento de voz encerra os segmentos de voz ativos para evitar que continuem a ser acumulados. Ao reativá-lo, os usuários já conectados podem precisar mudar de canal ou reconectar para a coleta começar novamente.

## Contadores automáticos

Um contador usa um canal de voz ou palco cujo nome o bot atualiza quando o valor muda. As métricas disponíveis são:

- `member_count` - contagem de membros do servidor;
- `human_members` - membros humanos;
- `bot_members` - bots;
- `voice_members` - membros conectados à voz;
- `messages_period` - mensagens na janela configurada;
- `active_members_period` - membros únicos ativos na janela configurada.

Os formatos aceitam os marcadores `{value}`, `{label}`, `{goal}` e `{percent}`. O nome final respeita o limite de 100 caracteres do Discord; sem uma meta, `{percent}` é apresentado como `n/a`. O worker é periódico, respeita intervalos mínimos, evita editar nomes que não mudaram, armazena último resultado/erro e não afirma sucesso quando a API do Discord recusa a atualização. Há limite de 100 contadores por servidor.

## Cargos baseados em atividade

Regras persistidas podem combinar um mínimo de mensagens, segundos em voz e dias ativos, cada qual com sua própria janela temporal. Concessão e remoção são registradas em auditoria. A remoção só ocorre quando `remove_when_unqualified` foi explicitamente habilitado.

O worker revalida a existência do cargo, permissões, hierarquia e permissões privilegiadas do cargo antes de agir. Cargos `@everyone`, gerenciados, acima do cargo do bot ou com permissões sensíveis não são automatizados. Há limite de 100 regras por servidor. O resultado da validação e erros recentes ficam disponíveis na configuração da regra.

## API

As rotas ficam sob `/api/v1/guilds/{guild_id}` e usam a autorização de gerente do servidor já existente:

- `GET /analytics?period=24h|7d|30d|90d` - relatório geral; também aceita `start` e `end` juntos para intervalos personalizados, limitados a 366 dias.
- `GET /analytics/channels/{channel_id}?days=7` - série e resumo de um canal.
- `GET /analytics/members/{user_id}?days=30` - estatísticas individuais, sujeitas à configuração de privacidade.
- `GET /analytics/settings` e `PATCH /analytics/settings` - consultar/atualizar filtros.
- `GET /analytics/counters`, `POST /analytics/counters`, `PATCH /analytics/counters/{counter_id}`, `DELETE /analytics/counters/{counter_id}` - gerenciar contadores.
- `GET /analytics/role-rules`, `POST /analytics/role-rules`, `PATCH /analytics/role-rules/{rule_id}`, `DELETE /analytics/role-rules/{rule_id}` - gerenciar regras de cargos.

As operações administrativas passam pela autorização de servidor e pelo sistema de auditoria. IDs Discord são tratados como strings no JSON da interface para evitar perda de precisão em JavaScript.

## Migração e atualização

Foi adicionada a migração `0016_advanced_analytics`, sucessora da cadeia existente. Ela adiciona os campos necessários para o rastreamento de voz, as tabelas de métricas/configurações/contadores/regras e os índices de consulta; não apaga o histórico existente.

No Windows, preserve o `.env` já configurado e execute a migração com o interpretador do projeto:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

Para desenvolvimento web, instale as dependências bloqueadas na pasta `web` e então execute:

```powershell
npm --prefix web ci
npm --prefix web run lint
npm --prefix web run build
```

Antes de aplicar a migração em produção, faça backup do banco e valide a atualização em uma cópia de homologação. Não exclua nem recrie o volume PostgreSQL para aplicar a migração.

## Validação e limitações

A suíte automatizada Python da implementação passou com 356 testes; `compileall`, as auditorias do repositório/segurança e a matriz de comandos também são executadas durante a revisão. Neste ambiente, não foi possível concluir o lint/build web porque o registry npm não terminou a instalação das dependências. Também não houve teste ao vivo contra um servidor Discord real, PostgreSQL ou Redis. Portanto, a implantação deve ser validada em homologação, especialmente as permissões reais para renomear canais, a hierarquia de cargos e a migração PostgreSQL.
