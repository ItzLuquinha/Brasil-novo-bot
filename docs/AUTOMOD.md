# AutoMod

O AutoMod do BN Bot executa a avaliação diretamente no evento de mensagem e grava cada ocorrência relevante em PostgreSQL. O estado temporário usado por spam, flood, duplicação e similaridade utiliza Redis, com fallback local para manter uma instância única operacional quando Redis estiver indisponível.

## Ativação

Use `/automod setup` para ativar o AutoMod e criar as regras padrão. Use `/automod enable` ou `/automod disable` para alternar o módulo depois disso.

## Regras

Os tipos disponíveis são `spam`, `flood`, `duplicate`, `similarity`, `link`, `invite`, `forbidden_word`, `caps`, `mentions`, `attachments` e `suspicious`.

As ações disponíveis são `none`, `delete`, `warn`, `timeout`, `kick` e `ban`.

Cada regra pode limitar sua execução por lista de IDs de canais e cargos. Quando ambos existem, a mensagem precisa estar em um dos canais e o autor precisa possuir pelo menos um dos cargos definidos.

A prioridade determina qual regra controla a ação final quando mais de uma regra corresponder. Em empate, a severidade interna da detecção desempata.

## Configurações de exemplo

Spam:

```json
{"max_messages":5,"window_seconds":8,"timeout_seconds":60}
```

Flood:

```json
{"max_messages":8,"window_seconds":4,"timeout_seconds":120}
```

Similaridade:

```json
{"threshold":0.92,"min_length":20}
```

Links com bloqueio geral:

```json
{"block_all":true}
```

Links somente fora de uma allowlist:

```json
{"block_all":false,"allowed_domains":["example.com","docs.example.com"]}
```

Palavras proibidas:

```json
{"words":["palavra1","palavra2"]}
```

Caps:

```json
{"min_letters":20,"ratio":0.75}
```

Menções:

```json
{"max_total":5,"max_roles":3,"timeout_seconds":60}
```

Arquivos:

```json
{"max_files":5,"max_total_size_mb":25,"blocked_extensions":["exe","scr","bat","cmd","msi"]}
```

Comportamento suspeito:

```json
{"threshold":60,"new_account_seconds":604800,"new_member_seconds":86400}
```

## Whitelist e blacklist

Entradas podem ser cadastradas como `user`, `channel`, `role`, `word` ou `domain`.

A whitelist de usuário, canal ou cargo interrompe a avaliação do AutoMod para aquela mensagem. A whitelist de domínio é específica para regras de link e convite, evitando que um domínio permitido desative outras proteções.

A blacklist possui uma ação global configurável por `/automod list-action`. Uma correspondência de blacklist recebe prioridade máxima e não depende de outra regra de detecção.

## Comandos

`/automod setup`

`/automod enable`

`/automod disable`

`/automod status`

`/automod rules`

`/automod rule-add`

`/automod rule-update`

`/automod rule-delete`

`/automod list-add`

`/automod list-remove`

`/automod lists`

`/automod list-action`

## Persistência

`automod_rules` guarda as regras. `automod_list_entries` guarda whitelist e blacklist. `automod_events` registra a mensagem, regra, ação, motivo, prioridade efetiva e sinais detectados.

## Segurança operacional

A avaliação nunca confia somente na interface do dashboard. Permissões de configuração são verificadas pelos comandos Discord e pelas rotas autenticadas do dashboard. A ação de banimento por comportamento suspeito somente acontece quando uma regra com ação `ban` é explicitamente configurada.
