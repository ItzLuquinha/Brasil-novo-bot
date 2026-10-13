# Commands

## Utilidades

`/ping`, `/uptime`, `/botinfo`, `/serverinfo`, `/userinfo` e `/avatar` mostram informações rápidas. `/history` exibe até 50 comandos recentes e exige Manage Server.

`/purge` aceita de 1 a 1000 mensagens a analisar/remover. O Discord exclui em lotes de até 100; mensagens com mais de 14 dias são excluídas individualmente. Configure a auditoria em `/admin purge-log canal:#canal-de-logs`; `/admin purge-log` consulta a configuração atual e `/admin purge-log desativar:true` desativa os registros. O bot precisa de View Channel, Send Messages e Attach Files no canal de logs. A auditoria inclui apenas mensagens cuja exclusão foi confirmada pela API.

`/tutorial` abre um painel privado com instruções de uso geral, economia, progressão, dashboard e estatísticas, moderação, comunidade, segurança, administração e diversão. Cada categoria explica a função dos comandos e exibe a permissão exigida. `/remind` agenda um lembrete em minutos, entregue no canal atual ou por mensagem direta. `/dashboard` envia um botão privado que abre o painel web configurado em `DASHBOARD_URL`; os recursos administrativos dependem das permissões da conta no servidor. `/msg` permite escrever `@nome` para mencionar um membro quando o nome corresponder a uma única pessoa do servidor. Se o nome não for encontrado ou corresponder a várias pessoas, ele permanece como texto e o bot informa o motivo. Menções a `@everyone`, `@here` e cargos não disparam notificações por esse comando.

## Economia e progressão

`/balance`, `/bank`, `/deposit`, `/withdraw`, `/pay`, `/daily`, `/weekly`, `/shop`, `/buy`, `/sell`, `/inventory`, `/transactions`, `/jobs`, `/job`, `/work`, `/profile`, `/rep`, `/reps` e `/leaderboard` cobrem economia e progressão.

## Moderação

`/warn`, `/t-warn`, `/warns`, `/unwarn`, `/clearwarns`, `/timeout`, `/untimeout`, `/unmute`, `/kick`, `/ban`, `/unban` e `/purge` exigem as permissões correspondentes do Discord.


## AutoMod

`/automod setup` creates the default protection policy and activates AutoMod.

`/automod enable` and `/automod disable` control the module.

`/automod rules` lists configured rules.

`/automod rule-add` creates a rule with JSON configuration, priority and optional channel or role scope.

`/automod rule-update` changes action, configuration, priority, scope or enabled state.

`/automod rule-delete` removes a rule.

`/automod list-add`, `/automod list-remove` and `/automod lists` manage whitelist and blacklist entries for users, channels, roles, words and domains.

`/automod list-action` controls the action taken for a blacklist match.

## Anti-Raid

/antiraid setup
/antiraid enable
/antiraid disable
/antiraid configure
/antiraid status
/antiraid unlock


## Community

`/ticket` opens a private support channel. `/ticket-close`, `/ticket-reopen` and `/ticket-claim` operate tickets. `/ticket-config` configures the ticket category, staff roles and transcript channel.

`/suggest` publishes a suggestion with persistent community voting. `/suggestion-status` moves a suggestion through pending, analysis, approved, rejected or implemented.

`/report` registers a report with optional evidence. `/report-status` moves it through open, investigating, resolved or rejected. `/community-config` configures the suggestion and report channels.

`/giveaway create` creates a giveaway with duration, winner count, role requirements, minimum level and minimum messages. `/giveaway end` ends it immediately. `/giveaway reroll` selects another winner without reusing previous winners. `/giveaway cancel` cancels an active giveaway.

`/poll create` creates an interactive poll with 2 to 10 options. `/poll end` closes it immediately.

`/admin job-remove` remove uma vaga com autocomplete e confirmação. `/msg` envia uma mensagem do bot para um canal de texto ou tópico selecionado e exige a permissão Gerenciar Servidor.


## Economy

`/transactions` mostra o histórico financeiro do membro com filtros por entradas, saídas, transferências e compras. `/daily` e `/weekly` usam os valores configurados pelo administrador em `/admin rewards`, incluindo bônus de sequência. `/shop`, `/buy`, `/sell` e `/inventory` usam paginação e autocomplete para catálogos maiores.

## Administration

`/admin rewards` configura os valores base de daily e weekly e o bônus de sequência. `/admin shop-add` pode definir descrição, raridade, limite por membro, cooldown e janela de disponibilidade.

## Mensagens administrativas

`/msg canal mensagem` envia o texto informado pelo próprio bot para um canal de texto/anúncios ou tópico selecionado. Somente membros com **Gerenciar Servidor** podem executar o comando; o bot também precisa ter acesso ao destino e permissão para enviar mensagens. Menções são desativadas no envio para evitar notificações em massa. A sincronização de comandos acontece ao iniciar o bot e remove comandos remotos que já não existem no código.

## Visibilidade dos comandos por permissão

Comandos protegidos por permissões nativas do Discord usam `default_permissions` além dos checks executados pelo bot. Isso faz o Discord ocultar o comando no seletor para membros sem a permissão padrão necessária, enquanto os checks do backend continuam sendo a proteção efetiva. Grupos como `/admin`, `/automod`, `/antiraid`, `/giveaway` e `/poll` são restringidos no nível do grupo, pois o Discord não permite definir visibilidade padrão individual para subcomandos.

Os comandos de equipe ligados à configuração `staff_role_ids` (`/ticket-reopen`, `/ticket-claim`, `/suggestion-status` e `/report-status`) também ficam restritos por padrão a `Gerenciar Servidor`. Se a equipe usar um cargo personalizado sem essa permissão, um administrador deve conceder acesso ao comando pelo Discord em **Configurações do servidor → Integrações → BN Bot → Permissões de comandos**. Isso é necessário porque a visibilidade padrão do Discord entende permissões nativas, não a lista privada de cargos armazenada pelo BN Bot. A validação de `is_staff` continua ativa mesmo depois de conceder uma exceção.
