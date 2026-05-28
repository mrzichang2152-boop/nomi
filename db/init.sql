CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS events (
  event_id UUID PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  raw_data JSONB NOT NULL,
  raw_data_private JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS semantic_events (
  id UUID PRIMARY KEY,
  event_id UUID UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
  intent TEXT,
  entities JSONB NOT NULL DEFAULT '{}'::jsonb,
  importance DOUBLE PRECISION NOT NULL DEFAULT 0,
  summary TEXT,
  model_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS timeline (
  id UUID PRIMARY KEY,
  date DATE NOT NULL,
  summary TEXT NOT NULL,
  source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS working_memory (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  expires_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS semantic_memory (
  id UUID PRIMARY KEY,
  memory_type TEXT NOT NULL,
  content JSONB NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
  source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS facts (
  id UUID PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(subject, predicate, object)
);

CREATE TABLE IF NOT EXISTS memory_states (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
  source_fact_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_vectors (
  id UUID PRIMARY KEY,
  event_id UUID UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS proactive_suggestions (
  id UUID PRIMARY KEY,
  source_event_id UUID UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  priority DOUBLE PRECISION NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assistant_conversations (
  id UUID PRIMARY KEY,
  client_type TEXT NOT NULL DEFAULT 'web',
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  active_task_id TEXT,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS assistant_turns (
  id UUID PRIMARY KEY,
  conversation_id UUID REFERENCES assistant_conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  event_id UUID UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
  suggestion_id UUID,
  tool_call_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finalized_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS context_snapshots (
  id UUID PRIMARY KEY,
  event_id UUID REFERENCES events(event_id) ON DELETE CASCADE,
  context_type TEXT NOT NULL,
  included_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  included_memory_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  included_agenda_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  reason TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agenda_items (
  id UUID PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'scheduled',
  certainty TEXT NOT NULL DEFAULT 'exact',
  time_window JSONB NOT NULL DEFAULT '{}'::jsonb,
  place TEXT,
  participants JSONB NOT NULL DEFAULT '[]'::jsonb,
  missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
  needs_clarification BOOLEAN NOT NULL DEFAULT FALSE,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
  source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agenda_item_versions (
  id UUID PRIMARY KEY,
  agenda_item_id UUID REFERENCES agenda_items(id) ON DELETE CASCADE,
  operation TEXT NOT NULL,
  previous_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  new_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason TEXT NOT NULL DEFAULT '',
  source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entities (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,
  name TEXT NOT NULL,
  aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(entity_type, name)
);

CREATE TABLE IF NOT EXISTS relationships (
  id UUID PRIMARY KEY,
  from_entity UUID REFERENCES entities(id) ON DELETE CASCADE,
  to_entity UUID REFERENCES entities(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  weight DOUBLE PRECISION NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(from_entity, to_entity, relation_type)
);

CREATE TABLE IF NOT EXISTS collector_health (
  collector TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  last_event_at TIMESTAMPTZ,
  last_injection_at TIMESTAMPTZ,
  error_count INTEGER NOT NULL DEFAULT 0,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS collector_settings (
  source TEXT PRIMARY KEY,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  paused_until TIMESTAMPTZ,
  reason TEXT NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_audit_log (
  id UUID PRIMARY KEY,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_source_idx ON events(source);
CREATE INDEX IF NOT EXISTS events_type_idx ON events(event_type);
CREATE INDEX IF NOT EXISTS events_timestamp_idx ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS semantic_events_intent_idx ON semantic_events(intent);
CREATE INDEX IF NOT EXISTS timeline_date_idx ON timeline(date DESC);
CREATE INDEX IF NOT EXISTS facts_predicate_idx ON facts(predicate);
CREATE INDEX IF NOT EXISTS facts_subject_idx ON facts(subject);
CREATE INDEX IF NOT EXISTS memory_states_updated_idx ON memory_states(updated_at DESC);
CREATE INDEX IF NOT EXISTS memory_vectors_embedding_idx ON memory_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS proactive_suggestions_status_idx ON proactive_suggestions(status, priority DESC);
CREATE INDEX IF NOT EXISTS assistant_turns_conversation_idx ON assistant_turns(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS assistant_turns_event_idx ON assistant_turns(event_id);
CREATE INDEX IF NOT EXISTS context_snapshots_event_idx ON context_snapshots(event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agenda_items_status_idx ON agenda_items(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS agenda_items_metadata_dedupe_idx ON agenda_items ((metadata->>'dedupe_key'));
CREATE INDEX IF NOT EXISTS collector_settings_enabled_idx ON collector_settings(enabled, paused_until);
CREATE INDEX IF NOT EXISTS memory_audit_log_target_idx ON memory_audit_log(target_type, target_id, created_at DESC);
