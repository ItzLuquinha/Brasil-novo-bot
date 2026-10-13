from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE guilds (
	id BIGINT NOT NULL,
	name VARCHAR(200) NOT NULL,
	icon_url VARCHAR(500),
	owner_id BIGINT,
	active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id BIGINT NOT NULL,
	username VARCHAR(200) NOT NULL,
	display_name VARCHAR(200) NOT NULL,
	avatar_url VARCHAR(500),
	banner_url VARCHAR(500),
	bot BOOLEAN NOT NULL,
	locale VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE achievements (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	key VARCHAR(100) NOT NULL,
	name VARCHAR(150) NOT NULL,
	description VARCHAR(500) NOT NULL,
	category VARCHAR(40) NOT NULL,
	secret BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, key),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE audit_logs (
	id BIGINT NOT NULL,
	guild_id BIGINT,
	executor_id BIGINT NOT NULL,
	action VARCHAR(120) NOT NULL,
	resource VARCHAR(120) NOT NULL,
	before_state JSON,
	after_state JSON,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE auto_responses (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	trigger_type VARCHAR(20) NOT NULL,
	trigger_value VARCHAR(500) NOT NULL,
	response JSON NOT NULL,
	channel_id BIGINT,
	cooldown_seconds INTEGER NOT NULL,
	priority INTEGER NOT NULL,
	enabled BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE automations (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	name VARCHAR(120) NOT NULL,
	trigger JSON NOT NULL,
	conditions JSON NOT NULL,
	actions JSON NOT NULL,
	enabled BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE backups (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	created_by BIGINT NOT NULL,
	storage_key VARCHAR(500) NOT NULL,
	checksum VARCHAR(128) NOT NULL,
	metadata_json JSON NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE channel_activity (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	channel_id BIGINT NOT NULL,
	bucket_start TIMESTAMP WITH TIME ZONE NOT NULL,
	metric VARCHAR(30) NOT NULL,
	value INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, channel_id, bucket_start, metric),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE cooldowns (
	id BIGINT NOT NULL,
	guild_id BIGINT,
	user_id BIGINT,
	key VARCHAR(120) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id, key),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE custom_commands (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	name VARCHAR(64) NOT NULL,
	response JSON NOT NULL,
	enabled BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, name),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE economy_accounts (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	wallet NUMERIC(18, 2) NOT NULL,
	bank NUMERIC(18, 2) NOT NULL,
	lifetime_earned NUMERIC(18, 2) NOT NULL,
	lifetime_spent NUMERIC(18, 2) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE economy_transactions (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	counterparty_user_id BIGINT,
	amount NUMERIC(18, 2) NOT NULL,
	kind VARCHAR(40) NOT NULL,
	note VARCHAR(500),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE experiences (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	total_xp BIGINT NOT NULL,
	level INTEGER NOT NULL,
	rewarded_level INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE giveaways (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	channel_id BIGINT NOT NULL,
	prize VARCHAR(300) NOT NULL,
	winners INTEGER NOT NULL,
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
	requirements JSON NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE guild_permissions (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	subject_type VARCHAR(20) NOT NULL,
	subject_id BIGINT NOT NULL,
	resource_type VARCHAR(20) NOT NULL,
	resource_id BIGINT,
	permission VARCHAR(120) NOT NULL,
	allowed BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE guild_settings (
	guild_id BIGINT NOT NULL,
	timezone VARCHAR(64) NOT NULL,
	locale VARCHAR(16) NOT NULL,
	economy_enabled BOOLEAN NOT NULL,
	levels_enabled BOOLEAN NOT NULL,
	analytics_enabled BOOLEAN NOT NULL,
	automod_enabled BOOLEAN NOT NULL,
	config JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (guild_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE integrations (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	provider VARCHAR(50) NOT NULL,
	config JSON NOT NULL,
	active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, provider),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE jobs (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	key VARCHAR(80) NOT NULL,
	name VARCHAR(100) NOT NULL,
	salary NUMERIC(18, 2) NOT NULL,
	xp_reward INTEGER NOT NULL,
	requirements JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, key),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE marriages (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_a_id BIGINT NOT NULL,
	user_b_id BIGINT NOT NULL,
	married_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_a_id),
	UNIQUE (guild_id, user_b_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE member_activity (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	bucket_start TIMESTAMP WITH TIME ZONE NOT NULL,
	metric VARCHAR(30) NOT NULL,
	value INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id, bucket_start, metric),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE members (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	joined_at TIMESTAMP WITH TIME ZONE,
	left_at TIMESTAMP WITH TIME ZONE,
	activity_score INTEGER NOT NULL,
	message_count INTEGER NOT NULL,
	voice_seconds INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE message_logs (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	channel_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	message_id BIGINT NOT NULL,
	event VARCHAR(30) NOT NULL,
	content_length INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE moderation_logs (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	actor_id BIGINT NOT NULL,
	target_id BIGINT,
	kind VARCHAR(50) NOT NULL,
	reason VARCHAR(500),
	data JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE notifications (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	provider VARCHAR(40) NOT NULL,
	source_key VARCHAR(200) NOT NULL,
	channel_id BIGINT NOT NULL,
	config JSON NOT NULL,
	active BOOLEAN NOT NULL,
	last_seen TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE pets (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	species VARCHAR(80) NOT NULL,
	name VARCHAR(100) NOT NULL,
	rarity VARCHAR(30) NOT NULL,
	level INTEGER NOT NULL,
	xp INTEGER NOT NULL,
	hunger INTEGER NOT NULL,
	energy INTEGER NOT NULL,
	happiness INTEGER NOT NULL,
	abilities JSON NOT NULL,
	equipped BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE polls (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	channel_id BIGINT NOT NULL,
	question TEXT NOT NULL,
	options JSON NOT NULL,
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE punishments (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	moderator_id BIGINT NOT NULL,
	kind VARCHAR(40) NOT NULL,
	reason VARCHAR(500),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	metadata_json JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE quests (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	key VARCHAR(80) NOT NULL,
	name VARCHAR(150) NOT NULL,
	kind VARCHAR(30) NOT NULL,
	objective JSON NOT NULL,
	reward JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, key),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE reminders (
	id BIGINT NOT NULL,
	guild_id BIGINT,
	user_id BIGINT NOT NULL,
	channel_id BIGINT,
	message TEXT NOT NULL,
	due_at TIMESTAMP WITH TIME ZONE NOT NULL,
	sent_at TIMESTAMP WITH TIME ZONE,
	delivery VARCHAR(10) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE reports (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	reporter_id BIGINT NOT NULL,
	reported_id BIGINT NOT NULL,
	reason TEXT NOT NULL,
	evidence TEXT,
	channel_id BIGINT,
	status VARCHAR(30) NOT NULL,
	resolver_id BIGINT,
	resolution TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE reputation_events (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	giver_id BIGINT NOT NULL,
	receiver_id BIGINT NOT NULL,
	amount INTEGER NOT NULL,
	reason VARCHAR(500),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE reputations (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	score INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE reward_claims (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	kind VARCHAR(20) NOT NULL,
	claim_key VARCHAR(40) NOT NULL,
	streak INTEGER NOT NULL,
	amount NUMERIC(18, 2) NOT NULL,
	claimed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id, kind, claim_key),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE shop_items (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	name VARCHAR(100) NOT NULL,
	description VARCHAR(500) NOT NULL,
	category VARCHAR(50) NOT NULL,
	rarity VARCHAR(30) NOT NULL,
	price NUMERIC(18, 2) NOT NULL,
	stock INTEGER,
	stack_limit INTEGER NOT NULL,
	metadata_json JSON NOT NULL,
	available_from TIMESTAMP WITH TIME ZONE,
	available_until TIMESTAMP WITH TIME ZONE,
	cooldown_seconds INTEGER,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, name),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE suggestions (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	author_id BIGINT NOT NULL,
	content TEXT NOT NULL,
	status VARCHAR(30) NOT NULL,
	upvotes INTEGER NOT NULL,
	downvotes INTEGER NOT NULL,
	staff_note TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE temporary_roles (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	reason VARCHAR(500),
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE tickets (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	channel_id BIGINT,
	opener_id BIGINT NOT NULL,
	assignee_id BIGINT,
	category VARCHAR(80) NOT NULL,
	priority VARCHAR(20) NOT NULL,
	status VARCHAR(20) NOT NULL,
	reason VARCHAR(500),
	transcript TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE verifications (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	verified BOOLEAN NOT NULL,
	verified_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE warnings (
	id BIGINT NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	moderator_id BIGINT NOT NULL,
	reason VARCHAR(500) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	active BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
);

CREATE TABLE inventory_items (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	shop_item_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	metadata_json JSON NOT NULL,
	acquired_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id, shop_item_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE,
	FOREIGN KEY(shop_item_id) REFERENCES shop_items (id) ON DELETE CASCADE
);

CREATE TABLE user_achievements (
	id SERIAL NOT NULL,
	achievement_id INTEGER NOT NULL,
	user_id BIGINT NOT NULL,
	earned_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (achievement_id, user_id),
	FOREIGN KEY(achievement_id) REFERENCES achievements (id) ON DELETE CASCADE
);

CREATE TABLE user_jobs (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	job_id INTEGER NOT NULL,
	level INTEGER NOT NULL,
	xp INTEGER NOT NULL,
	last_work_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (guild_id, user_id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE,
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE TABLE user_quests (
	id SERIAL NOT NULL,
	guild_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	quest_id INTEGER NOT NULL,
	progress JSON NOT NULL,
	completed BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE,
	FOREIGN KEY(quest_id) REFERENCES quests (id) ON DELETE CASCADE
);

CREATE INDEX ix_economy_rank ON economy_accounts (guild_id, wallet, bank);

CREATE INDEX ix_economy_transactions_guild_user_created ON economy_transactions (guild_id, user_id, created_at);

CREATE INDEX ix_experience_rank ON experiences (guild_id, total_xp);

CREATE INDEX ix_member_activity_guild_bucket ON member_activity (guild_id, bucket_start);

CREATE INDEX ix_members_guild_activity ON members (guild_id, activity_score);

CREATE INDEX ix_reputation_rank ON reputations (guild_id, score);

CREATE INDEX ix_reward_claims_user_kind ON reward_claims (guild_id, user_id, kind, claimed_at);

CREATE INDEX ix_warnings_guild_user_active ON warnings (guild_id, user_id, active);""")


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "user_quests" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user_jobs" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user_achievements" CASCADE')
    op.execute('DROP TABLE IF EXISTS "inventory_items" CASCADE')
    op.execute('DROP TABLE IF EXISTS "warnings" CASCADE')
    op.execute('DROP TABLE IF EXISTS "verifications" CASCADE')
    op.execute('DROP TABLE IF EXISTS "tickets" CASCADE')
    op.execute('DROP TABLE IF EXISTS "temporary_roles" CASCADE')
    op.execute('DROP TABLE IF EXISTS "suggestions" CASCADE')
    op.execute('DROP TABLE IF EXISTS "shop_items" CASCADE')
    op.execute('DROP TABLE IF EXISTS "reward_claims" CASCADE')
    op.execute('DROP TABLE IF EXISTS "reputations" CASCADE')
    op.execute('DROP TABLE IF EXISTS "reputation_events" CASCADE')
    op.execute('DROP TABLE IF EXISTS "reports" CASCADE')
    op.execute('DROP TABLE IF EXISTS "reminders" CASCADE')
    op.execute('DROP TABLE IF EXISTS "quests" CASCADE')
    op.execute('DROP TABLE IF EXISTS "punishments" CASCADE')
    op.execute('DROP TABLE IF EXISTS "polls" CASCADE')
    op.execute('DROP TABLE IF EXISTS "pets" CASCADE')
    op.execute('DROP TABLE IF EXISTS "notifications" CASCADE')
    op.execute('DROP TABLE IF EXISTS "moderation_logs" CASCADE')
    op.execute('DROP TABLE IF EXISTS "message_logs" CASCADE')
    op.execute('DROP TABLE IF EXISTS "members" CASCADE')
    op.execute('DROP TABLE IF EXISTS "member_activity" CASCADE')
    op.execute('DROP TABLE IF EXISTS "marriages" CASCADE')
    op.execute('DROP TABLE IF EXISTS "jobs" CASCADE')
    op.execute('DROP TABLE IF EXISTS "integrations" CASCADE')
    op.execute('DROP TABLE IF EXISTS "guild_settings" CASCADE')
    op.execute('DROP TABLE IF EXISTS "guild_permissions" CASCADE')
    op.execute('DROP TABLE IF EXISTS "giveaways" CASCADE')
    op.execute('DROP TABLE IF EXISTS "experiences" CASCADE')
    op.execute('DROP TABLE IF EXISTS "economy_transactions" CASCADE')
    op.execute('DROP TABLE IF EXISTS "economy_accounts" CASCADE')
    op.execute('DROP TABLE IF EXISTS "custom_commands" CASCADE')
    op.execute('DROP TABLE IF EXISTS "cooldowns" CASCADE')
    op.execute('DROP TABLE IF EXISTS "channel_activity" CASCADE')
    op.execute('DROP TABLE IF EXISTS "backups" CASCADE')
    op.execute('DROP TABLE IF EXISTS "automations" CASCADE')
    op.execute('DROP TABLE IF EXISTS "auto_responses" CASCADE')
    op.execute('DROP TABLE IF EXISTS "audit_logs" CASCADE')
    op.execute('DROP TABLE IF EXISTS "achievements" CASCADE')
    op.execute('DROP TABLE IF EXISTS "users" CASCADE')
    op.execute('DROP TABLE IF EXISTS "guilds" CASCADE')
