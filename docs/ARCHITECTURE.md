# Architecture

BN Bot follows a modular monolith design. Discord events and dashboard routes call application services. Services own business rules. Repositories own persistence access. SQLAlchemy models define the relational domain.

## Boundaries

Discord -> commands/events -> services -> repositories -> PostgreSQL

Dashboard -> API routes -> services -> repositories -> PostgreSQL

Redis is used only for ephemeral coordination such as cooldowns, rate limiting and distributed locks.

## Data isolation

All guild-scoped domain tables include `guild_id` and use foreign keys to `guilds`. Queries are scoped by guild before data is returned. Dashboard authorization independently verifies guild membership and permissions against Discord.

## Money safety

Economy mutations run in a database transaction and lock the account rows with `SELECT ... FOR UPDATE`. Transaction records are written in the same transaction as balance changes.

## Time

User-facing schedule operations convert through IANA time zones. Timestamps stored in PostgreSQL are UTC.

## Deployment layout

The bot and dashboard can run in the same Python deployment or as two processes sharing the same PostgreSQL database and Redis instance. Business services remain process-agnostic.
