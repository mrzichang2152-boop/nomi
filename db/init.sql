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

CREATE TABLE IF NOT EXISTS proactive_candidates (
  id UUID PRIMARY KEY,
  candidate_type TEXT NOT NULL,
  agenda_item_id UUID,
  event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  scores JSONB NOT NULL DEFAULT '{}'::jsonb,
  decision TEXT NOT NULL DEFAULT 'pending',
  cooldown_key TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_feedback (
  id UUID PRIMARY KEY,
  suggestion_id UUID,
  action TEXT NOT NULL,
  rating DOUBLE PRECISION,
  reason TEXT NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS chat_attachments (
  id UUID PRIMARY KEY,
  client_upload_id TEXT,
  sha256 TEXT,
  original_filename TEXT NOT NULL,
  safe_filename TEXT NOT NULL,
  declared_mime_type TEXT,
  detected_mime_type TEXT,
  extension TEXT,
  byte_size BIGINT NOT NULL DEFAULT 0,
  storage_relative_path TEXT,
  status TEXT NOT NULL,
  lifecycle TEXT NOT NULL DEFAULT 'draft',
  parser_kind TEXT,
  processing_version TEXT NOT NULL DEFAULT 'attachment-v1',
  error_code TEXT,
  error_detail_safe TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  stored_at TIMESTAMPTZ,
  processed_at TIMESTAMPTZ,
  attached_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  CHECK (status IN ('receiving', 'stored', 'processing', 'ready', 'rejected', 'failed')),
  CHECK (lifecycle IN ('draft', 'attached', 'deleted')),
  CHECK (byte_size >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS chat_attachments_client_upload_id_uidx
ON chat_attachments(client_upload_id)
WHERE client_upload_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS chat_attachments_expiry_idx
ON chat_attachments(expires_at)
WHERE lifecycle = 'draft';

CREATE INDEX IF NOT EXISTS chat_attachments_sha256_idx
ON chat_attachments(sha256, processing_version)
WHERE sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS chat_attachment_derivatives (
  id UUID PRIMARY KEY,
  attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  mime_type TEXT,
  storage_relative_path TEXT,
  byte_size BIGINT NOT NULL DEFAULT 0,
  locator JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  processing_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (byte_size >= 0)
);

CREATE INDEX IF NOT EXISTS chat_attachment_derivatives_attachment_idx
ON chat_attachment_derivatives(attachment_id, kind, created_at);

CREATE TABLE IF NOT EXISTS chat_attachment_chunks (
  id UUID PRIMARY KEY,
  attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  locator JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash TEXT NOT NULL,
  embedding vector(384),
  processing_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (attachment_id, processing_version, ordinal),
  CHECK (ordinal >= 0),
  CHECK (token_count >= 0)
);

CREATE INDEX IF NOT EXISTS chat_attachment_chunks_attachment_idx
ON chat_attachment_chunks(attachment_id, processing_version, ordinal);

CREATE INDEX IF NOT EXISTS chat_attachment_chunks_text_idx
ON chat_attachment_chunks USING GIN (to_tsvector('simple', text));

CREATE TABLE IF NOT EXISTS assistant_turn_attachments (
  turn_id UUID NOT NULL REFERENCES assistant_turns(id) ON DELETE CASCADE,
  attachment_id UUID NOT NULL REFERENCES chat_attachments(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  purpose TEXT NOT NULL DEFAULT 'user_provided',
  PRIMARY KEY (turn_id, attachment_id),
  UNIQUE (turn_id, ordinal),
  CHECK (ordinal >= 0)
);

CREATE INDEX IF NOT EXISTS assistant_turn_attachments_attachment_idx
ON assistant_turn_attachments(attachment_id, turn_id);

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

CREATE TABLE IF NOT EXISTS agenda_reminders (
  id UUID PRIMARY KEY,
  agenda_item_id UUID REFERENCES agenda_items(id) ON DELETE CASCADE,
  starts_at TIMESTAMPTZ NOT NULL,
  remind_at TIMESTAMPTZ NOT NULL,
  lead_minutes INTEGER NOT NULL,
  dedupe_key TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ
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

CREATE TABLE IF NOT EXISTS task_route_traces (
  id UUID PRIMARY KEY,
  request TEXT NOT NULL,
  route_type TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  pipeline_id TEXT,
  risk_permission TEXT NOT NULL,
  confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
  task_route_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
  openclaw_task_packet JSONB,
  clarification JSONB,
  context_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  conversation_id TEXT,
  suggestion_id TEXT,
  agenda_item_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_execution_results (
  id UUID PRIMARY KEY,
  task_trace_id TEXT,
  request TEXT NOT NULL,
  route_type TEXT NOT NULL,
  capability_id TEXT,
  pipeline_id TEXT,
  status TEXT NOT NULL,
  required_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  resolved_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
  missing_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  risk JSONB NOT NULL DEFAULT '{}'::jsonb,
  execution_guard JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  conversation_id TEXT,
  suggestion_id TEXT,
  agenda_item_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_writeback_events (
  id UUID PRIMARY KEY,
  pipeline_execution_id TEXT,
  task_trace_id TEXT,
  pipeline_id TEXT,
  target TEXT NOT NULL,
  operation TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_quarantine (
  id UUID PRIMARY KEY,
  event_id TEXT,
  dedupe_key TEXT,
  source TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL DEFAULT '',
  event_timestamp TEXT,
  schema_errors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  raw_event JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS duplicate_skip (
  id UUID PRIMARY KEY,
  event_id TEXT,
  dedupe_key TEXT,
  duplicate_of TEXT,
  source TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_items (
  id TEXT PRIMARY KEY,
  source_event_id TEXT,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_entities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
  id UUID PRIMARY KEY,
  source_id TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  relation_type TEXT NOT NULL DEFAULT '',
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_vector_retries (
  id UUID PRIMARY KEY,
  source_event_id TEXT,
  chunk_id TEXT,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_snapshot_plans (
  id UUID PRIMARY KEY,
  request_or_event_id TEXT NOT NULL DEFAULT '',
  current_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS internal_todos (
  id UUID PRIMARY KEY,
  task_title TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  due_window JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS internal_reminders (
  id UUID PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'planned_internal',
  due_window JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_call_traces (
  id UUID PRIMARY KEY,
  task_id TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL DEFAULT '',
  call_status TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS confirmation_ledger (
  id UUID PRIMARY KEY,
  task_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '',
  confirm_action TEXT NOT NULL DEFAULT '',
  final_user_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'required',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_health_metrics (
  id UUID PRIMARY KEY,
  pipeline_id TEXT,
  status TEXT NOT NULL DEFAULT '',
  applied_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS search_audit (
  id UUID PRIMARY KEY,
  pipeline_id TEXT NOT NULL DEFAULT '',
  query TEXT NOT NULL DEFAULT '',
  scope TEXT NOT NULL DEFAULT '',
  result_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS career_profiles (
  id TEXT PRIMARY KEY,
  headline TEXT NOT NULL DEFAULT '',
  target_roles TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  target_locations TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  skills TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS career_resumes (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL DEFAULT '',
  file_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  parsed_text TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_opportunities (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'tracked',
  fit_score DOUBLE PRECISION,
  requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resume_versions (
  id TEXT PRIMARY KEY,
  base_resume_id TEXT NOT NULL DEFAULT '',
  target_job_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_applications (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'tracked',
  stage TEXT NOT NULL DEFAULT '',
  next_step TEXT NOT NULL DEFAULT '',
  application_action TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account_connections (
  provider TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'not_connected',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS composio_sessions (
  id UUID PRIMARY KEY,
  user_id TEXT NOT NULL,
  session_kind TEXT NOT NULL,
  session_id TEXT NOT NULL UNIQUE,
  mcp_url TEXT NOT NULL DEFAULT '',
  mcp_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled_toolkits TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  tags JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS composio_connect_requests (
  id UUID PRIMARY KEY,
  user_id TEXT NOT NULL,
  toolkit_slug TEXT NOT NULL,
  session_kind TEXT NOT NULL,
  session_id TEXT NOT NULL DEFAULT '',
  connection_request_id TEXT NOT NULL DEFAULT '',
  redirect_url TEXT NOT NULL DEFAULT '',
  connected_account_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'link_created',
  expires_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS composio_toolkits (
  slug TEXT NOT NULL,
  session_kind TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  logo TEXT NOT NULL DEFAULT '',
  is_connected BOOLEAN NOT NULL DEFAULT FALSE,
  connected_account_id TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL DEFAULT '',
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (slug, session_kind)
);

CREATE TABLE IF NOT EXISTS composio_tool_invocations (
  id UUID PRIMARY KEY,
  task_trace_id TEXT,
  toolkit_slug TEXT NOT NULL DEFAULT '',
  tool_slug TEXT NOT NULL DEFAULT '',
  session_kind TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  request JSONB NOT NULL DEFAULT '{}'::jsonb,
  response JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS composio_triggers (
  id UUID PRIMARY KEY,
  trigger_id TEXT NOT NULL DEFAULT '',
  trigger_slug TEXT NOT NULL DEFAULT '',
  toolkit_slug TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS route_cache (
  id UUID PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT '',
  destination TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
CREATE INDEX IF NOT EXISTS proactive_suggestions_dedupe_idx ON proactive_suggestions ((metadata->>'dedupe_key'), status, updated_at DESC);
CREATE INDEX IF NOT EXISTS proactive_candidates_decision_idx ON proactive_candidates(decision, created_at DESC);
CREATE INDEX IF NOT EXISTS user_feedback_suggestion_idx ON user_feedback(suggestion_id, created_at DESC);
CREATE INDEX IF NOT EXISTS assistant_turns_conversation_idx ON assistant_turns(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS assistant_turns_event_idx ON assistant_turns(event_id);
CREATE INDEX IF NOT EXISTS context_snapshots_event_idx ON context_snapshots(event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agenda_items_status_idx ON agenda_items(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS agenda_items_metadata_dedupe_idx ON agenda_items ((metadata->>'dedupe_key'));
CREATE UNIQUE INDEX IF NOT EXISTS agenda_reminders_dedupe_key_idx ON agenda_reminders(dedupe_key);
CREATE INDEX IF NOT EXISTS agenda_reminders_due_idx ON agenda_reminders(status, remind_at);
CREATE INDEX IF NOT EXISTS collector_settings_enabled_idx ON collector_settings(enabled, paused_until);
CREATE INDEX IF NOT EXISTS memory_audit_log_target_idx ON memory_audit_log(target_type, target_id, created_at DESC);
CREATE INDEX IF NOT EXISTS task_route_traces_created_idx ON task_route_traces(created_at DESC);
CREATE INDEX IF NOT EXISTS task_route_traces_route_idx ON task_route_traces(route_type, capability_id, created_at DESC);
CREATE INDEX IF NOT EXISTS task_route_traces_source_event_idx ON task_route_traces USING GIN(source_event_ids);
CREATE INDEX IF NOT EXISTS task_route_traces_conversation_idx ON task_route_traces(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_execution_results_trace_idx ON pipeline_execution_results(task_trace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_execution_results_source_event_idx ON pipeline_execution_results USING GIN(source_event_ids);
CREATE INDEX IF NOT EXISTS pipeline_execution_results_conversation_idx ON pipeline_execution_results(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_writeback_events_trace_idx ON pipeline_writeback_events(task_trace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_writeback_events_target_idx ON pipeline_writeback_events(target, status, created_at DESC);
CREATE INDEX IF NOT EXISTS event_quarantine_source_idx ON event_quarantine(source, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS duplicate_skip_dedupe_idx ON duplicate_skip(dedupe_key, created_at DESC);
CREATE INDEX IF NOT EXISTS memory_items_source_event_idx ON memory_items(source_event_id);
CREATE INDEX IF NOT EXISTS knowledge_entities_name_idx ON knowledge_entities(name);
CREATE INDEX IF NOT EXISTS knowledge_edges_source_idx ON knowledge_edges(source_id, relation_type);
CREATE INDEX IF NOT EXISTS internal_todos_status_idx ON internal_todos(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS internal_reminders_status_idx ON internal_reminders(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS provider_call_traces_task_idx ON provider_call_traces(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS confirmation_ledger_task_idx ON confirmation_ledger(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_health_metrics_pipeline_idx ON pipeline_health_metrics(pipeline_id, created_at DESC);
CREATE INDEX IF NOT EXISTS search_audit_query_idx ON search_audit(query, created_at DESC);
CREATE INDEX IF NOT EXISTS career_profiles_updated_idx ON career_profiles(updated_at DESC);
CREATE INDEX IF NOT EXISTS career_resumes_updated_idx ON career_resumes(updated_at DESC);
CREATE INDEX IF NOT EXISTS job_opportunities_status_idx ON job_opportunities(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS job_opportunities_fit_idx ON job_opportunities(fit_score DESC);
CREATE INDEX IF NOT EXISTS resume_versions_job_idx ON resume_versions(target_job_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS job_applications_stage_idx ON job_applications(stage, updated_at DESC);
CREATE INDEX IF NOT EXISTS job_applications_job_idx ON job_applications(job_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS composio_sessions_user_kind_idx ON composio_sessions(user_id, session_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS composio_connect_requests_toolkit_idx ON composio_connect_requests(toolkit_slug, status, created_at DESC);
CREATE INDEX IF NOT EXISTS composio_tool_invocations_tool_idx ON composio_tool_invocations(toolkit_slug, tool_slug, created_at DESC);
CREATE INDEX IF NOT EXISTS composio_triggers_slug_idx ON composio_triggers(trigger_slug, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS route_cache_destination_idx ON route_cache(destination, updated_at DESC);
