# Instalação do BN Bot no Discord como App

O BN Bot usa os comandos de barra do Discord como Application Commands. Os comandos seguros para uso como User Install são registrados globalmente e podem funcionar em servidores onde o aplicativo foi instalado na conta do usuário, além de DMs e conversas privadas.

## Portal do Desenvolvedor

Na aplicação do BN Bot, abra a área de instalação e habilite os dois contextos de instalação:

- Guild Install para adicionar o bot normalmente a um servidor.
- User Install para adicionar o aplicativo à conta de um usuário.

O Install Link deve permanecer habilitado. O link padrão do Discord pode ser usado.

Para Guild Install, mantenha os escopos `bot` e `applications.commands` e configure as permissões do bot de acordo com a instalação do servidor.

Para User Install, o escopo usado é `applications.commands`. Uma User Install não transforma o aplicativo em membro de um servidor e não concede ao aplicativo permissão para executar ações de moderação no servidor.

## Comandos disponíveis em User Install

O projeto libera como User Install apenas comandos que não precisam do bot estar instalado como membro de um servidor:

- `/ping`
- `/uptime`
- `/botinfo`
- `/avatar`
- `/tutorial`
- `/coinflip`
- `/dice`
- `/rps`
- `/eightball`

Comandos de moderação, administração, economia ligada ao servidor, tickets, AutoMod, Anti-Raid e outros fluxos dependentes do servidor continuam limitados ao Guild Install.

## DM do bot

Ao receber uma DM de um usuário, o BN Bot apresenta dois botões:

- Adicionar ao servidor: instalação Guild Install com `bot` + `applications.commands`.
- Adicionar como App: instalação User Install com `applications.commands`.

A mensagem de instalação tem rate limit por usuário para evitar spam.

## Sincronização

Em produção, os comandos são sincronizados globalmente. Em desenvolvimento, os comandos compatíveis com User Install também recebem uma sincronização global separada, enquanto o conjunto completo continua sendo sincronizado na guild de desenvolvimento.

As opções de instalação e os contextos também são gravados nos objetos dos Application Commands. O padrão do `CommandTree` é seguro: Guild Install + contexto de guild. Um comando só entra em User Install quando é explicitamente marcado como compatível.
