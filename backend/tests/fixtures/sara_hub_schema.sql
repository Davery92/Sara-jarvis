--
-- PostgreSQL database dump
--

\restrict wqEwBaDybiH7Y8UCbf661FBZVd0M74UcU3L8djU5r2LavnDjiuFlKEby8XtGnXy

-- Dumped from database version 16.10 (Debian 16.10-1.pgdg12+1)
-- Dumped by pg_dump version 16.10 (Debian 16.10-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: inboxkind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.inboxkind AS ENUM (
    'INSIGHT',
    'ALERT',
    'REMINDER',
    'SUGGESTION'
);


--
-- Name: inboxstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.inboxstatus AS ENUM (
    'NEW',
    'READ',
    'ARCHIVED'
);


--
-- Name: taskkind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taskkind AS ENUM (
    'RESEARCH',
    'DRAFT',
    'COMPARE',
    'SUMMARIZE',
    'ANALYZE'
);


--
-- Name: taskstate; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taskstate AS ENUM (
    'QUEUED',
    'RUNNING',
    'WAITING_CONFIRM',
    'DONE',
    'FAILED',
    'CANCELLED'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: achievement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.achievement (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    type character varying NOT NULL,
    title character varying NOT NULL,
    description text,
    icon character varying,
    earned_at timestamp with time zone DEFAULT now(),
    celebrated boolean DEFAULT false
);


--
-- Name: TABLE achievement; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.achievement IS 'User achievements for gamification and rapport building';


--
-- Name: action_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_ledger (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    standing_order_id integer,
    action_type character varying(50) NOT NULL,
    action_config jsonb DEFAULT '{}'::jsonb,
    trigger_context jsonb DEFAULT '{}'::jsonb,
    success boolean DEFAULT true,
    executed_at timestamp with time zone DEFAULT now() NOT NULL,
    undo_available boolean DEFAULT false,
    undo_expires_at timestamp with time zone,
    undone boolean DEFAULT false,
    undone_at timestamp with time zone,
    source character varying(50) DEFAULT 'standing_order'::character varying
);


--
-- Name: action_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.action_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: action_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.action_ledger_id_seq OWNED BY public.action_ledger.id;


--
-- Name: action_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_log (
    action_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    action_type character varying(100) NOT NULL,
    action_content text,
    context_snapshot jsonb,
    karma_state_at_action jsonb,
    outcome_status character varying(20) DEFAULT 'pending'::character varying,
    outcome_details text,
    outcome_recorded_at timestamp without time zone,
    feedback_source character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: action_receipt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_receipt (
    action_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    source_intent_id character varying(255),
    action_type character varying(100) NOT NULL,
    target text,
    permission_tier character varying(30) NOT NULL,
    reversible boolean DEFAULT false NOT NULL,
    undo_expires_at timestamp with time zone,
    idempotency_key character varying(255),
    status character varying(20) NOT NULL,
    evidence_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    artifact_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    executed_at timestamp with time zone,
    correlation_id character varying(64),
    source_table character varying(50),
    source_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    ledger_id integer,
    undone boolean DEFAULT false NOT NULL
);


--
-- Name: action_why_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_why_trace (
    id bigint NOT NULL,
    user_id character varying NOT NULL,
    kind character varying NOT NULL,
    category character varying,
    priority character varying,
    source character varying,
    topic character varying,
    decision character varying,
    reason character varying,
    chain jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: action_why_trace_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.action_why_trace_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: action_why_trace_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.action_why_trace_id_seq OWNED BY public.action_why_trace.id;


--
-- Name: active_workout_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.active_workout_session (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    template_id character varying(36),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    current_exercise_index integer DEFAULT 0 NOT NULL,
    current_set_index integer DEFAULT 0 NOT NULL,
    workout_snapshot jsonb,
    rest_timer_started_at timestamp with time zone,
    rest_timer_duration_seconds integer,
    total_sets_completed integer DEFAULT 0 NOT NULL,
    total_volume numeric(12,2) DEFAULT '0'::numeric NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    version bigint DEFAULT '1'::bigint NOT NULL,
    origin_device character varying(20),
    start_attempt_id character varying(64),
    healthkit_state character varying(20),
    healthkit_workout_uuid character varying(128),
    healthkit_activity_type character varying(80),
    healthkit_started_at timestamp with time zone,
    healthkit_ended_at timestamp with time zone,
    last_device_sync_at timestamp with time zone
);


--
-- Name: activity_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_session (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    session_start timestamp without time zone NOT NULL,
    session_end timestamp without time zone,
    idle_duration integer,
    active_view character varying,
    interaction_count integer,
    quick_sweep_triggered boolean,
    standard_sweep_triggered boolean,
    digest_sweep_triggered boolean,
    insights_generated integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_run_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_log (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    run_duration_ms integer,
    context_summary text,
    actions_taken jsonb DEFAULT '[]'::jsonb,
    notifications_sent jsonb DEFAULT '[]'::jsonb,
    observations text,
    conversation_flags jsonb DEFAULT '[]'::jsonb,
    handoff_note text,
    watching_for text,
    david_state_snapshot jsonb,
    journal_entry_id character varying(255),
    source character varying(50) DEFAULT 'unified_heartbeat'::character varying,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    run_metadata jsonb DEFAULT '{}'::jsonb,
    run_uuid character varying(255),
    quiet_mode_active boolean DEFAULT false
);


--
-- Name: agent_run_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_run_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_run_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_run_log_id_seq OWNED BY public.agent_run_log.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: anchor_point; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.anchor_point (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    topic_id character varying NOT NULL,
    anchor_concept character varying(500) NOT NULL,
    anchor_domain character varying(255) NOT NULL,
    bridge_description text,
    confidence double precision DEFAULT 0.5,
    validated boolean DEFAULT false,
    rejected boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: app_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_settings (
    key character varying(255) NOT NULL,
    value text,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by character varying(255)
);


--
-- Name: app_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_user (
    id character varying NOT NULL,
    email character varying NOT NULL,
    password_hash character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: app_user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_user_role (
    user_id character varying NOT NULL,
    role character varying(32) DEFAULT 'user'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_app_user_role CHECK (((role)::text = ANY ((ARRAY['user'::character varying, 'admin'::character varying, 'owner'::character varying])::text[])))
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    conversation_id character varying(36),
    episode_id character varying(36),
    artifact_type character varying(50) NOT NULL,
    title character varying(255) NOT NULL,
    content jsonb NOT NULL,
    artifact_metadata jsonb,
    is_pinned boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: attention_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attention_item (
    attention_item_id uuid DEFAULT gen_random_uuid() NOT NULL,
    outbound_intent_id uuid NOT NULL,
    decision character varying(30) NOT NULL,
    rendered_text text,
    delivered_channels jsonb DEFAULT '[]'::jsonb NOT NULL,
    delivered_at timestamp with time zone,
    acknowledged boolean DEFAULT false NOT NULL,
    correlation_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: attention_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attention_policy (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    domain character varying NOT NULL,
    context character varying NOT NULL,
    threshold double precision DEFAULT 0.5 NOT NULL,
    domain_prior double precision DEFAULT 0.5 NOT NULL,
    explore_rate double precision DEFAULT 0.1 NOT NULL,
    anomaly_floor double precision DEFAULT 0.85 NOT NULL,
    surface_budget integer,
    n_surfaced bigint DEFAULT 0,
    n_engaged bigint DEFAULT 0,
    n_ignored bigint DEFAULT 0,
    n_dismissed bigint DEFAULT 0,
    last_updated timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: attention_policy_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attention_policy_snapshot (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    domain character varying NOT NULL,
    context character varying NOT NULL,
    threshold double precision NOT NULL,
    captured_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: automation_execution_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_execution_log (
    id integer NOT NULL,
    task_id character varying NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    step_executed integer NOT NULL,
    action_primitive character varying(50) NOT NULL,
    action_details jsonb,
    status character varying(20) NOT NULL,
    result jsonb,
    error_message text
);


--
-- Name: automation_execution_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.automation_execution_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: automation_execution_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.automation_execution_log_id_seq OWNED BY public.automation_execution_log.id;


--
-- Name: automation_state_store; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_state_store (
    id integer NOT NULL,
    task_id character varying NOT NULL,
    key character varying(255) NOT NULL,
    value jsonb,
    previous_value jsonb,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: automation_state_store_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.automation_state_store_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: automation_state_store_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.automation_state_store_id_seq OWNED BY public.automation_state_store.id;


--
-- Name: automation_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_task (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying(255) NOT NULL,
    original_intent text NOT NULL,
    description text,
    schedule_definition jsonb NOT NULL,
    actions jsonb NOT NULL,
    conditions jsonb DEFAULT '[]'::jsonb,
    status character varying(20) DEFAULT 'pending_confirmation'::character varying NOT NULL,
    next_wake_at timestamp with time zone,
    current_step integer DEFAULT 0,
    step_state jsonb DEFAULT '{}'::jsonb,
    expires_at timestamp with time zone,
    max_executions integer,
    execution_count integer DEFAULT 0,
    consecutive_errors integer DEFAULT 0,
    last_error text,
    created_at timestamp with time zone DEFAULT now(),
    confirmed_at timestamp with time zone,
    last_executed_at timestamp with time zone
);


--
-- Name: autonomous_insight; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.autonomous_insight (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    insight_type character varying NOT NULL,
    sweep_type character varying NOT NULL,
    priority_score double precision NOT NULL,
    title character varying NOT NULL,
    message text NOT NULL,
    action_suggestion character varying,
    related_data text,
    surfaced_at timestamp without time zone,
    user_action character varying,
    feedback_score integer,
    generated_at timestamp without time zone DEFAULT now(),
    expires_at timestamp without time zone
);


--
-- Name: autonomy_action_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.autonomy_action_trace (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_uuid uuid,
    run_id integer,
    user_id character varying(255) NOT NULL,
    source character varying(50) DEFAULT 'unified_agent'::character varying NOT NULL,
    action_name character varying(255) NOT NULL,
    action_args jsonb,
    risk_tier smallint DEFAULT 0 NOT NULL,
    decision character varying(20) DEFAULT 'allow'::character varying NOT NULL,
    decision_reason text,
    simulation jsonb,
    result jsonb,
    success boolean DEFAULT true NOT NULL,
    error_message text,
    step_index integer DEFAULT 0 NOT NULL,
    idempotency_key character varying(255),
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: autonomy_mission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.autonomy_mission (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    title text NOT NULL,
    description text,
    source character varying(50) DEFAULT 'user'::character varying NOT NULL,
    state character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    total_steps integer DEFAULT 0 NOT NULL,
    completed_steps integer DEFAULT 0 NOT NULL,
    current_step_index integer DEFAULT 0 NOT NULL,
    requires_confirmation boolean DEFAULT false NOT NULL,
    confirmed_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: autonomy_mission_step; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.autonomy_mission_step (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mission_id uuid NOT NULL,
    step_index integer NOT NULL,
    action_name character varying(255) NOT NULL,
    action_args jsonb DEFAULT '{}'::jsonb,
    description text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    result jsonb,
    error_message text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: autonomy_trust; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.autonomy_trust (
    action_class character varying NOT NULL,
    granted_level integer DEFAULT 1 NOT NULL,
    executions integer DEFAULT 0 NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    accepts integer DEFAULT 0 NOT NULL,
    declines integer DEFAULT 0 NOT NULL,
    last_demoted_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: background_sweep; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.background_sweep (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    sweep_type character varying NOT NULL,
    triggered_by character varying NOT NULL,
    execution_time_ms integer NOT NULL,
    insights_generated integer,
    errors_encountered text,
    episodes_analyzed integer,
    notes_analyzed integer,
    patterns_found text,
    executed_at timestamp without time zone DEFAULT now()
);


--
-- Name: background_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.background_task (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    status character varying NOT NULL,
    task_type character varying NOT NULL,
    original_query text NOT NULL,
    result_note_id character varying,
    workspace_folder_id character varying,
    clarification_question text,
    clarification_response text,
    error_message text,
    task_metadata jsonb,
    created_at timestamp without time zone DEFAULT now(),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: behavioral_pattern; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.behavioral_pattern (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    trigger_type character varying(50) NOT NULL,
    trigger_conditions jsonb NOT NULL,
    action_type character varying(50) NOT NULL,
    action_payload jsonb NOT NULL,
    description text,
    source_context text,
    category character varying(50),
    evidence_dates date[] DEFAULT '{}'::date[],
    evidence_count integer DEFAULT 0,
    confidence double precision DEFAULT 0.0,
    min_occurrences integer DEFAULT 2,
    status character varying(20) DEFAULT 'learning'::character varying,
    times_suggested integer DEFAULT 0,
    times_accepted integer DEFAULT 0,
    times_rejected integer DEFAULT 0,
    last_triggered_at timestamp without time zone,
    last_suggested_at timestamp without time zone,
    last_accepted_at timestamp without time zone,
    user_feedback text,
    suggestion_window_start time without time zone DEFAULT '08:00:00'::time without time zone,
    suggestion_window_end time without time zone DEFAULT '21:00:00'::time without time zone,
    cooldown_hours integer DEFAULT 24,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ladder_status character varying DEFAULT 'observed'::character varying NOT NULL
);


--
-- Name: body_capability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.body_capability (
    name character varying(100) NOT NULL,
    kind character varying(30) NOT NULL,
    version character varying(100),
    capabilities jsonb DEFAULT '[]'::jsonb NOT NULL,
    capability_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: body_state_calibration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.body_state_calibration (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    estimate_type character varying NOT NULL,
    estimated_value double precision NOT NULL,
    estimated_label character varying,
    feedback_type character varying NOT NULL,
    user_response text,
    correction_direction character varying,
    correction_magnitude double precision,
    hours_since_meal double precision,
    hours_since_sleep double precision,
    time_of_day double precision,
    affected_coefficient character varying,
    coefficient_adjustment double precision,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: body_state_coefficients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.body_state_coefficients (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    blood_sugar_decay_rate double precision DEFAULT 1.0,
    meal_sustain_factor double precision DEFAULT 1.0,
    sleep_target_hours double precision DEFAULT 7.5,
    sleep_debt_sensitivity double precision DEFAULT 1.0,
    circadian_phase_shift double precision DEFAULT 0.0,
    recovery_rate_multiplier double precision DEFAULT 1.0,
    stress_tolerance double precision DEFAULT 1.0,
    calibration_count integer DEFAULT 0,
    last_calibrated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: briefing_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.briefing_settings (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    morning_enabled integer,
    morning_time character varying,
    evening_enabled integer,
    evening_time character varying,
    delivery_methods json DEFAULT '["push"]'::json NOT NULL,
    include_weather boolean DEFAULT false,
    include_calendar boolean DEFAULT true,
    include_goals integer,
    include_suggestions integer,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    include_recovery integer,
    include_schedule integer,
    include_workout_rec integer,
    include_accomplishments integer,
    include_insights integer,
    include_reflection integer
);


--
-- Name: calendar_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calendar_event (
    id text NOT NULL,
    user_id text NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone NOT NULL,
    location text DEFAULT ''::text,
    all_day boolean DEFAULT false,
    reminder_minutes integer,
    is_completed boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    source character varying(50) DEFAULT 'sara'::character varying NOT NULL,
    ios_event_id character varying(255),
    ios_calendar_id character varying(255),
    ios_calendar_name character varying(255),
    read_only boolean DEFAULT false NOT NULL,
    rrule text,
    recurring_event_id text,
    attendees jsonb DEFAULT '[]'::jsonb NOT NULL,
    organizer character varying(255),
    owner character varying(64),
    owner_relation character varying(32)
);


--
-- Name: candidate_skill; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.candidate_skill (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    instructions text,
    contexts jsonb DEFAULT '[]'::jsonb,
    priority integer DEFAULT 50,
    status character varying(50) DEFAULT 'pending'::character varying,
    source_mission_id character varying(36),
    source_task_id character varying(36),
    vm_artifacts jsonb DEFAULT '{}'::jsonb,
    review_notes text,
    created_at timestamp with time zone DEFAULT now(),
    reviewed_at timestamp with time zone,
    times_used integer DEFAULT 0 NOT NULL,
    times_succeeded integer DEFAULT 0 NOT NULL
);


--
-- Name: cardio_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cardio_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    activity_type character varying NOT NULL,
    title character varying,
    duration_minutes double precision NOT NULL,
    distance_miles double precision,
    avg_hr integer,
    max_hr integer,
    zone character varying,
    calories_burned double precision,
    rpe integer,
    source character varying,
    tabata_detail json,
    notes text,
    session_date date NOT NULL,
    logged_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: cardio_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cardio_settings (
    user_id character varying NOT NULL,
    weekly_min_minutes integer,
    weekly_max_minutes integer,
    steps_floor integer,
    menu json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: chat_turn_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_turn_trace (
    id bigint NOT NULL,
    user_id character varying(64),
    conversation_id character varying(64),
    client_message_id character varying(64),
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    first_token_ms integer,
    total_ms integer,
    prompt_tokens_first integer,
    tool_count integer,
    rounds integer,
    tools_called jsonb DEFAULT '[]'::jsonb NOT NULL,
    ended_by character varying(16) DEFAULT 'model'::character varying NOT NULL,
    context_chars integer,
    reply_chars integer
);


--
-- Name: chat_turn_trace_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chat_turn_trace_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_turn_trace_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chat_turn_trace_id_seq OWNED BY public.chat_turn_trace.id;


--
-- Name: chess_coaching_progress; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chess_coaching_progress (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    topics_completed jsonb DEFAULT '[]'::jsonb,
    current_topic character varying(100),
    openings_studied jsonb DEFAULT '[]'::jsonb,
    tactical_motifs jsonb DEFAULT '[]'::jsonb,
    endgames_practiced jsonb DEFAULT '[]'::jsonb,
    total_coaching_sessions integer DEFAULT 0,
    last_session_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: chess_game; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chess_game (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying,
    player_color character varying(10) NOT NULL,
    fen text DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'::text,
    move_history jsonb DEFAULT '[]'::jsonb,
    move_history_san jsonb DEFAULT '[]'::jsonb,
    result character varying(10),
    termination character varying(50),
    pgn text,
    analysis jsonb,
    started_at timestamp with time zone DEFAULT now(),
    ended_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: chess_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chess_stats (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    games_played integer DEFAULT 0,
    wins integer DEFAULT 0,
    losses integer DEFAULT 0,
    draws integer DEFAULT 0,
    current_level integer DEFAULT 1,
    estimated_elo integer DEFAULT 600,
    win_rate_at_level double precision DEFAULT 0.0,
    games_at_level integer DEFAULT 0,
    common_openings jsonb DEFAULT '{}'::jsonb,
    strengths jsonb DEFAULT '[]'::jsonb,
    weaknesses jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: code_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.code_session (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    conversation_id character varying,
    dev_project_id character varying,
    repo_owner character varying(255),
    repo_name character varying(255),
    branch character varying(255),
    workdir character varying(1000),
    state character varying(20) NOT NULL,
    active boolean NOT NULL,
    cancel_requested boolean NOT NULL,
    transcript jsonb NOT NULL,
    session_log text,
    queue jsonb NOT NULL,
    turns integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    last_active_at timestamp with time zone DEFAULT now()
);


--
-- Name: composed_utterance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.composed_utterance (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    candidate_id uuid NOT NULL,
    user_id character varying(255) NOT NULL,
    text text NOT NULL,
    refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    urgency character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    slot character varying(20),
    review_verdict character varying(10) NOT NULL,
    review_reason text,
    final_text text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone,
    delivery_result jsonb,
    CONSTRAINT ck_composed_utterance_verdict CHECK (((review_verdict)::text = ANY ((ARRAY['approve'::character varying, 'edit'::character varying, 'kill'::character varying])::text[])))
);


--
-- Name: consolidation_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consolidation_config (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    config_key character varying(100) NOT NULL,
    config_value jsonb NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by character varying(50) DEFAULT 'system'::character varying
);


--
-- Name: consolidation_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consolidation_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consolidation_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consolidation_config_id_seq OWNED BY public.consolidation_config.id;


--
-- Name: consolidation_discards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consolidation_discards (
    id integer NOT NULL,
    consolidation_run_id uuid,
    raw_entry_id character varying(255) NOT NULL,
    stream_type character varying(50) NOT NULL,
    content_preview text,
    relevance_score double precision,
    discard_reason character varying(100) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: consolidation_discards_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consolidation_discards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consolidation_discards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consolidation_discards_id_seq OWNED BY public.consolidation_discards.id;


--
-- Name: consolidation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consolidation_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    started_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone,
    window_start timestamp without time zone NOT NULL,
    window_end timestamp without time zone NOT NULL,
    raw_entries_processed integer DEFAULT 0,
    entries_kept integer DEFAULT 0,
    entries_discarded integer DEFAULT 0,
    status character varying(20) DEFAULT 'running'::character varying,
    error_message text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: context_modes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_modes (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    current_mode character varying,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: context_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_snapshots (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    snapshot_data json NOT NULL,
    snapshot_date date NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: context_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.context_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: context_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.context_snapshots_id_seq OWNED BY public.context_snapshots.id;


--
-- Name: context_window; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_window (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    window_type character varying NOT NULL,
    parameters text NOT NULL,
    last_used timestamp without time zone,
    use_count integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: conversation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying,
    summary text,
    total_messages integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    enriched_through_episode_id text,
    enriched_through_at timestamp with time zone,
    enrichment_status text DEFAULT 'idle'::text,
    enrichment_attempts integer DEFAULT 0,
    enrichment_last_error text,
    enrichment_updated_at timestamp with time zone
);


--
-- Name: conversation_thread; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_thread (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    summary text,
    auto_generated boolean DEFAULT false,
    started_at timestamp with time zone DEFAULT now(),
    last_activity timestamp with time zone DEFAULT now(),
    message_count integer DEFAULT 0,
    tags text[],
    archived boolean DEFAULT false
);


--
-- Name: TABLE conversation_thread; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.conversation_thread IS 'Stores conversation threading for organized chat history';


--
-- Name: conversation_turn; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_turn (
    id character varying NOT NULL,
    conversation_id character varying NOT NULL,
    user_id character varying NOT NULL,
    role character varying NOT NULL,
    content text NOT NULL,
    message_index integer NOT NULL,
    embedding text,
    created_at timestamp without time zone DEFAULT now(),
    client_message_id character varying(64)
);


--
-- Name: correction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.correction (
    id bigint NOT NULL,
    user_id character varying(255) NOT NULL,
    correction_type character varying(32) NOT NULL,
    subject character varying(255) NOT NULL,
    predicate character varying(128),
    old_value text,
    new_value text,
    scope character varying(32) DEFAULT 'permanent'::character varying NOT NULL,
    effective_from timestamp with time zone DEFAULT now() NOT NULL,
    effective_until timestamp with time zone,
    superseded_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_turn text,
    explicit boolean DEFAULT true NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: correction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.correction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: correction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.correction_id_seq OWNED BY public.correction.id;


--
-- Name: correlation_pattern; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.correlation_pattern (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(36) NOT NULL,
    pattern_type character varying(50) NOT NULL,
    pattern_category character varying(100) NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    narrative text,
    source_domains jsonb NOT NULL,
    metric_a character varying(100),
    metric_b character varying(100),
    correlation_pairs jsonb,
    correlation_coefficient double precision,
    sample_size integer NOT NULL,
    confidence double precision NOT NULL,
    p_value double precision,
    effect_size double precision,
    status character varying(20) NOT NULL,
    first_detected_at timestamp with time zone DEFAULT now(),
    last_validated_at timestamp with time zone DEFAULT now(),
    last_evidence_at timestamp with time zone,
    validation_count integer NOT NULL,
    invalidation_count integer NOT NULL,
    temporal_lag_hours integer,
    temporal_window character varying(20),
    time_of_day_start integer,
    time_of_day_end integer,
    day_of_week_pattern integer[],
    threshold_a double precision,
    threshold_b double precision,
    threshold_direction character varying(20),
    user_feedback character varying(20),
    surfaced_count integer NOT NULL,
    last_surfaced_at timestamp with time zone,
    embedding public.vector(1024),
    evidence jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: daily_briefings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_briefings (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    briefing_type character varying NOT NULL,
    briefing_date timestamp without time zone NOT NULL,
    content text NOT NULL,
    delivered integer,
    read integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: daily_briefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_briefs (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    brief_date date NOT NULL,
    sections jsonb,
    generated_at timestamp with time zone DEFAULT now(),
    generation_duration_ms integer,
    calendar_events_count integer,
    reminders_count integer,
    insights_count integer,
    dream_highlights_count integer,
    cache_key character varying(100),
    cache_expires_at timestamp with time zone,
    viewed_at timestamp with time zone,
    pinned_items jsonb
);


--
-- Name: daily_recovery_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_recovery_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    log_date date NOT NULL,
    hrv integer,
    heart_rate integer,
    sleep_hours numeric(4,2),
    soreness_level integer,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    body_weight numeric(5,2),
    weight_unit character varying(3) DEFAULT 'lbs'::character varying,
    CONSTRAINT daily_recovery_log_soreness_level_check CHECK (((soreness_level >= 1) AND (soreness_level <= 10)))
);


--
-- Name: daily_reflections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_reflections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying NOT NULL,
    reflection_date date NOT NULL,
    responses jsonb DEFAULT '{}'::jsonb NOT NULL,
    insights_generated jsonb DEFAULT '{}'::jsonb,
    mood_score integer,
    reflection_duration_minutes integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: daily_rhythm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_rhythm (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    rhythm_key character varying(50) NOT NULL,
    day_scope character varying(10) DEFAULT 'weekday'::character varying NOT NULL,
    window_start time without time zone,
    window_end time without time zone,
    median_time time without time zone,
    confidence double precision DEFAULT '0'::double precision NOT NULL,
    sample_count integer DEFAULT 0 NOT NULL,
    variance_minutes integer,
    evidence jsonb,
    computed_at timestamp with time zone DEFAULT now()
);


--
-- Name: daily_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_task (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    description text,
    task_date date DEFAULT CURRENT_DATE NOT NULL,
    priority character varying DEFAULT 'normal'::character varying,
    is_completed boolean DEFAULT false,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: day_replay_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.day_replay_cache (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    replay_date date NOT NULL,
    replay_data jsonb NOT NULL,
    summary text,
    data_sources text[],
    episode_count integer DEFAULT 0,
    automation_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: day_type_override; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.day_type_override (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    override_date date NOT NULL,
    day_type character varying(16) NOT NULL,
    note text,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: day_type_override_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.day_type_override_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: day_type_override_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.day_type_override_id_seq OWNED BY public.day_type_override.id;


--
-- Name: desktop_focus_span; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.desktop_focus_span (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    device_id character varying,
    app character varying,
    "window" character varying,
    domain character varying,
    derived_state character varying,
    start_ts timestamp with time zone,
    end_ts timestamp with time zone,
    duration_seconds integer DEFAULT 0 NOT NULL,
    keyboard_events integer DEFAULT 0 NOT NULL,
    mouse_events integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: dev_project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dev_project (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    name character varying(255) NOT NULL,
    prefix character varying(10) NOT NULL,
    description text,
    tech_stack character varying(500),
    business_context character varying(500),
    github_repo_owner character varying(255),
    github_repo_name character varying(255),
    github_installation_id character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    next_task_number integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_registration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_registration (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    device_name character varying(100) NOT NULL,
    device_token character varying(256) NOT NULL,
    device_type character varying(50) NOT NULL,
    last_seen timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: directive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directive (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    text text NOT NULL,
    category character varying(32) DEFAULT 'general'::character varying NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: directive_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directive_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directive_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directive_id_seq OWNED BY public.directive.id;


--
-- Name: doc_chunk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.doc_chunk (
    id character varying NOT NULL,
    file_id character varying NOT NULL,
    chunk_idx integer NOT NULL,
    text text NOT NULL,
    breadcrumb character varying,
    embedding public.vector(1024) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    filename character varying NOT NULL,
    original_filename character varying NOT NULL,
    file_path character varying NOT NULL,
    file_size integer NOT NULL,
    mime_type character varying NOT NULL,
    content_text text,
    is_processed character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    title character varying(255),
    category character varying DEFAULT 'general'::character varying
);


--
-- Name: document_chunk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_chunk (
    id character varying NOT NULL,
    document_id character varying NOT NULL,
    user_id character varying NOT NULL,
    chunk_text text NOT NULL,
    chunk_index integer NOT NULL,
    embedding text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: dream_insight; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dream_insight (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    dream_date timestamp without time zone NOT NULL,
    insight_type character varying NOT NULL,
    confidence double precision NOT NULL,
    title character varying NOT NULL,
    content text NOT NULL,
    related_episodes text,
    surfaced_at timestamp without time zone,
    user_feedback character varying,
    created_at timestamp without time zone DEFAULT now(),
    embedding public.vector(1024),
    surface_strategy character varying(50) DEFAULT 'contextual'::character varying,
    evidence text,
    expiry_at timestamp without time zone,
    surfaced_count integer DEFAULT 0,
    last_surfaced_at timestamp without time zone
);


--
-- Name: email; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    mailbox character varying NOT NULL,
    conversation_id character varying,
    subject character varying NOT NULL,
    sender_email character varying NOT NULL,
    sender_name character varying,
    received_at timestamp with time zone NOT NULL,
    importance character varying DEFAULT 'normal'::character varying,
    is_read boolean DEFAULT false,
    internet_message_id character varying,
    parent_folder_id character varying,
    body_preview text,
    body_text text,
    body_html text,
    to_recipients jsonb DEFAULT '[]'::jsonb,
    cc_recipients jsonb DEFAULT '[]'::jsonb,
    category character varying,
    importance_score double precision DEFAULT 0.0,
    summary text,
    action_required boolean DEFAULT false,
    analyzed_at timestamp with time zone,
    notification_sent boolean DEFAULT false,
    notification_sent_at timestamp with time zone,
    synced_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    has_meeting boolean DEFAULT false,
    calendar_event_id character varying,
    calendar_event_created_at timestamp with time zone
);


--
-- Name: email_attachment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_attachment (
    id character varying NOT NULL,
    email_id character varying NOT NULL,
    filename character varying NOT NULL,
    content_type character varying,
    size integer DEFAULT 0,
    is_inline boolean DEFAULT false,
    content_id character varying,
    minio_bucket character varying,
    minio_key character varying,
    is_riskninja_relevant boolean DEFAULT false,
    downloaded_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    filed_to_project_id character varying,
    filed_to_folder_id character varying,
    filed_to_file_id character varying,
    filed_at timestamp with time zone,
    filing_analysis text
);


--
-- Name: email_sync_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_sync_state (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    mailbox character varying NOT NULL,
    last_sync_at timestamp with time zone,
    last_sync_count integer DEFAULT 0,
    last_sync_errors integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: episode; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.episode (
    id character varying NOT NULL,
    conversation_id character varying,
    user_id character varying NOT NULL,
    role character varying NOT NULL,
    content text NOT NULL,
    importance double precision,
    emotional_tone text,
    topics text,
    context_tags text,
    access_count integer,
    last_accessed timestamp without time zone,
    memory_type character varying,
    source character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    meta jsonb DEFAULT '{}'::jsonb,
    emotion_metadata json,
    base_importance double precision,
    importance_last_updated timestamp with time zone,
    user_rating double precision,
    consolidated boolean DEFAULT false,
    embedding public.vector(1024),
    rating_boost double precision DEFAULT 0.0,
    exploration_bonus double precision DEFAULT 0.0,
    recall_relevance_ema double precision DEFAULT 0.5,
    client_message_id character varying(64),
    reply_to_client_message_id character varying(64)
);


--
-- Name: episode_rating; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.episode_rating (
    episode_id character varying NOT NULL,
    user_rating integer,
    rating_count integer,
    average_rating double precision,
    rating_sum integer,
    last_rated timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: episode_thread_mapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.episode_thread_mapping (
    episode_id character varying NOT NULL,
    thread_id character varying NOT NULL
);


--
-- Name: event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    starts_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    location character varying,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: event_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_log (
    id integer NOT NULL,
    event_id character varying NOT NULL,
    event_type character varying NOT NULL,
    user_id character varying NOT NULL,
    payload json DEFAULT '{}'::json NOT NULL,
    source character varying DEFAULT 'system'::character varying NOT NULL,
    metadata json DEFAULT '{}'::json NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: event_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_log_id_seq OWNED BY public.event_log.id;


--
-- Name: event_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_outbox (
    id integer NOT NULL,
    aggregate_type character varying NOT NULL,
    aggregate_id character varying NOT NULL,
    op character varying NOT NULL,
    payload text NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    processed_at timestamp without time zone,
    event_type character varying(50) DEFAULT 'legacy'::character varying NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    max_retries integer DEFAULT 5 NOT NULL,
    last_error text,
    next_retry_at timestamp with time zone
);


--
-- Name: event_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_outbox_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_outbox_id_seq OWNED BY public.event_outbox.id;


--
-- Name: exercise_library; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_library (
    id character varying NOT NULL,
    name character varying NOT NULL,
    movement_pattern character varying NOT NULL,
    muscle_groups json,
    equipment_required json,
    equipment_alternatives json,
    difficulty_level integer,
    injury_contraindications json,
    description text,
    instructions json,
    substitutions json,
    tags json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: exercise_pr; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_pr (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    exercise_name character varying(200) NOT NULL,
    weight numeric(8,2) NOT NULL,
    reps integer NOT NULL,
    estimated_1rm numeric(8,2) NOT NULL,
    achieved_at date NOT NULL,
    workout_set_id character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: external_workout; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_workout (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    source character varying(50) DEFAULT 'apple_health'::character varying NOT NULL,
    external_id character varying(128) NOT NULL,
    activity_type character varying(80) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone NOT NULL,
    duration_seconds integer NOT NULL,
    total_energy_kcal numeric(10,2),
    total_distance_m numeric(12,2),
    avg_heart_rate integer,
    max_heart_rate integer,
    min_heart_rate integer,
    hr_zones jsonb,
    workout_metadata jsonb,
    created_at timestamp with time zone DEFAULT now(),
    sara_session_id character varying(36)
);


--
-- Name: fatsecret_food_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fatsecret_food_cache (
    id character varying NOT NULL,
    fatsecret_id character varying(50) NOT NULL,
    name character varying(500) NOT NULL,
    brand character varying(200),
    food_type character varying(50),
    barcode character varying(50),
    servings_json jsonb,
    cached_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: fitness_daily_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_daily_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    log_date date NOT NULL,
    chat_count integer DEFAULT 0,
    food_entries integer DEFAULT 0,
    workout_sessions integer DEFAULT 0,
    notes_created integer DEFAULT 0,
    total_calories double precision,
    total_protein double precision,
    total_carbs double precision,
    total_fats double precision,
    total_exercises integer DEFAULT 0,
    total_sets integer DEFAULT 0,
    total_reps integer DEFAULT 0,
    summary text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fitness_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_goals (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    calories integer DEFAULT 2000,
    protein integer DEFAULT 150,
    carbs integer DEFAULT 200,
    fats integer DEFAULT 70,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: fitness_idempotency; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_idempotency (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    client_txn_id character varying NOT NULL,
    hash character varying,
    applied_at timestamp with time zone DEFAULT now(),
    succeeded boolean
);


--
-- Name: fitness_note; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_note (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying,
    content text NOT NULL,
    category character varying NOT NULL,
    embedding public.vector(1024),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: fitness_phase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_phase (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    goal character varying,
    parent_phase_id character varying,
    start_date date,
    end_date date,
    status character varying DEFAULT 'planned'::character varying,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    program_id character varying,
    order_index integer,
    duration_weeks integer,
    calories_target integer,
    protein_target integer,
    carbs_target integer,
    fat_target integer,
    training_days_per_week integer,
    deload_week integer,
    calories_training_day integer,
    calories_rest_day integer,
    carbs_training_day integer,
    carbs_rest_day integer,
    fat_training_day integer,
    fat_rest_day integer,
    daily_steps_target integer
);


--
-- Name: fitness_plan; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_plan (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    meta json,
    status character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: fitness_program; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_program (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying(200) NOT NULL,
    goal character varying(50) NOT NULL,
    start_date date,
    end_date date,
    is_active boolean,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    plan_markdown text,
    nutrition_guide text
);


--
-- Name: fitness_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_settings (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    system_prompt text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fitness_template; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fitness_template (
    id character varying NOT NULL,
    phase_id character varying,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    scheduled_days text,
    exercises text,
    order_in_phase integer DEFAULT 0,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    starting_weights json,
    day_of_week integer,
    rotation_order integer
);


--
-- Name: folder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.folder (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    parent_id character varying,
    sort_order integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: followup_thread; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.followup_thread (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    topic text NOT NULL,
    topic_category character varying(50),
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    opened_at timestamp with time zone DEFAULT now() NOT NULL,
    follow_up_after timestamp with time zone,
    follow_up_before timestamp with time zone,
    last_mentioned_at timestamp with time zone,
    resolved_at timestamp with time zone,
    mention_count integer DEFAULT 0,
    max_mentions integer DEFAULT 3,
    david_response character varying(20),
    original_context text,
    suggested_followup text,
    priority double precision DEFAULT 0.5,
    source character varying(50) DEFAULT 'chat'::character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: food_database; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.food_database (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    brand character varying(255),
    serving_size double precision DEFAULT 1 NOT NULL,
    serving_unit character varying(50) DEFAULT 'serving'::character varying NOT NULL,
    calories double precision,
    protein double precision,
    carbs double precision,
    fats double precision,
    fiber double precision,
    sugar double precision,
    sodium double precision,
    is_custom boolean DEFAULT true,
    source character varying(50) DEFAULT 'user'::character varying,
    barcode character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: food_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.food_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    meal_type character varying NOT NULL,
    food_items json NOT NULL,
    calories double precision,
    protein double precision,
    carbs double precision,
    fats double precision,
    notes text,
    logged_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    detailed_items jsonb,
    fatsecret_serving_id character varying(50),
    idempotency_key character varying
);


--
-- Name: food_log_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.food_log_item (
    id character varying NOT NULL,
    food_log_id character varying NOT NULL,
    fatsecret_food_id character varying,
    recipe_id character varying,
    custom_food_id character varying,
    serving_id character varying(100),
    serving_description character varying(200),
    quantity numeric(8,2),
    calories numeric(8,2),
    protein numeric(8,2),
    carbs numeric(8,2),
    fat numeric(8,2),
    fiber numeric(8,2),
    sugar numeric(8,2),
    sodium numeric(8,2),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: git_branch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.git_branch (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    name character varying(255) NOT NULL,
    last_commit_sha character varying(40),
    last_activity_at timestamp with time zone,
    is_default boolean DEFAULT false NOT NULL,
    is_merged boolean DEFAULT false NOT NULL,
    merged_at timestamp with time zone,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: git_commit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.git_commit (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    sha character varying(40) NOT NULL,
    message text NOT NULL,
    author_name character varying(255),
    author_email character varying(255),
    committed_at timestamp with time zone NOT NULL,
    branch character varying(255),
    files_changed jsonb,
    additions integer,
    deletions integer,
    raw_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: goal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.goal (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    description text,
    goal_type character varying NOT NULL,
    target_value double precision,
    current_value double precision,
    unit character varying,
    target_date date,
    status character varying DEFAULT 'active'::character varying NOT NULL,
    priority integer DEFAULT 5,
    metadata json DEFAULT '{}'::json NOT NULL,
    auto_tracking boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: goal_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.goal_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: goal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.goal_id_seq OWNED BY public.goal.id;


--
-- Name: goal_progress; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.goal_progress (
    id integer NOT NULL,
    goal_id integer NOT NULL,
    value double precision NOT NULL,
    notes text,
    source character varying NOT NULL,
    source_id character varying,
    logged_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: goal_progress_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.goal_progress_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: goal_progress_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.goal_progress_id_seq OWNED BY public.goal_progress.id;


--
-- Name: gtky_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gtky_sessions (
    id character varying NOT NULL,
    user_id character varying,
    question_pack character varying(50) NOT NULL,
    responses jsonb DEFAULT '{}'::jsonb NOT NULL,
    completed_at timestamp with time zone,
    session_metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: health_alert; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_alert (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    alert_type character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    message text NOT NULL,
    metric_data jsonb,
    notification_sent_at timestamp with time zone,
    acknowledged_at timestamp with time zone,
    insight_id character varying(36),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: health_baseline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_baseline (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    metric_type character varying(50) NOT NULL,
    period_type character varying(20) NOT NULL,
    average_value numeric(10,3) NOT NULL,
    std_deviation numeric(10,3),
    min_value numeric(10,3),
    max_value numeric(10,3),
    sample_count integer NOT NULL,
    calculated_at timestamp with time zone DEFAULT now(),
    period_end date NOT NULL
);


--
-- Name: health_insight; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_insight (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    insight_type character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    title character varying(500) NOT NULL,
    content text NOT NULL,
    evidence text,
    related_metrics jsonb,
    correlation_data jsonb,
    triggered_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    surfaced_at timestamp with time zone,
    surfaced_count integer NOT NULL,
    user_feedback character varying(50),
    notification_sent boolean NOT NULL,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: health_metric; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_metric (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    metric_type character varying(50) NOT NULL,
    value numeric(10,3) NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    source character varying(50) NOT NULL,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: health_weekly_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_weekly_report (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    week_start date NOT NULL,
    week_end date NOT NULL,
    stats_json jsonb NOT NULL,
    recovery_json jsonb,
    activity_json jsonb,
    headline character varying(255),
    full_markdown text,
    model_used character varying(100),
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error text,
    push_sent_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    note_id character varying
);


--
-- Name: heartbeat_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.heartbeat_items (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    item_type character varying(20) NOT NULL,
    description text NOT NULL,
    check_logic character varying(50) NOT NULL,
    expires_at timestamp with time zone,
    condition text,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(50) NOT NULL,
    source_context text,
    last_checked_at timestamp with time zone,
    last_triggered_at timestamp with time zone,
    times_checked integer DEFAULT 0,
    times_triggered integer DEFAULT 0,
    is_active boolean DEFAULT true,
    notification_channel character varying(20) DEFAULT 'both'::character varying,
    priority character varying(10) DEFAULT 'normal'::character varying
);


--
-- Name: heartbeat_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.heartbeat_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: heartbeat_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.heartbeat_items_id_seq OWNED BY public.heartbeat_items.id;


--
-- Name: heartbeat_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.heartbeat_logs (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    run_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    items_checked integer DEFAULT 0,
    items_triggered integer DEFAULT 0,
    triggered_item_ids integer[],
    actions_taken jsonb DEFAULT '[]'::jsonb,
    notification_sent boolean DEFAULT false,
    run_duration_ms integer,
    error_message text
);


--
-- Name: heartbeat_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.heartbeat_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: heartbeat_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.heartbeat_logs_id_seq OWNED BY public.heartbeat_logs.id;


--
-- Name: held_notification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.held_notification (
    id bigint NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    message text,
    category character varying,
    priority character varying,
    source character varying,
    topic character varying,
    payload jsonb,
    why_trace jsonb,
    held_reason character varying,
    held_at timestamp with time zone DEFAULT now() NOT NULL,
    deliver_after timestamp with time zone,
    status character varying DEFAULT 'held'::character varying NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: held_notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.held_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: held_notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.held_notification_id_seq OWNED BY public.held_notification.id;


--
-- Name: home_activity_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.home_activity_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    entity_id character varying(255) NOT NULL,
    friendly_name character varying(255),
    domain character varying(50) NOT NULL,
    from_state character varying(255),
    to_state character varying(255) NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    context jsonb,
    attributes jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: home_state_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.home_state_summary (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    hour_bucket timestamp without time zone NOT NULL,
    rooms_active jsonb,
    temperature_avg double precision,
    lights_on_count integer DEFAULT 0,
    motion_events integer DEFAULT 0,
    door_events integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: home_state_summary_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.home_state_summary_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: home_state_summary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.home_state_summary_id_seq OWNED BY public.home_state_summary.id;


--
-- Name: host_alert; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.host_alert (
    id integer NOT NULL,
    host_id character varying NOT NULL,
    rule character varying(48) NOT NULL,
    severity character varying(16) DEFAULT 'normal'::character varying NOT NULL,
    state character varying(16) DEFAULT 'firing'::character varying NOT NULL,
    detail jsonb,
    fired_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    notified boolean DEFAULT false NOT NULL
);


--
-- Name: host_alert_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.host_alert_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: host_alert_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.host_alert_id_seq OWNED BY public.host_alert.id;


--
-- Name: host_diag_command; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.host_diag_command (
    id integer NOT NULL,
    host_id character varying NOT NULL,
    user_id character varying,
    requested_by character varying(24) DEFAULT 'chat'::character varying NOT NULL,
    request_context character varying(255),
    argv jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    denied_reason text,
    exit_code integer,
    stdout text,
    stderr text,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    finished_at timestamp with time zone
);


--
-- Name: host_diag_command_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.host_diag_command_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: host_diag_command_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.host_diag_command_id_seq OWNED BY public.host_diag_command.id;


--
-- Name: host_metric; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.host_metric (
    id integer NOT NULL,
    host_id character varying NOT NULL,
    ts timestamp with time zone DEFAULT now(),
    cpu_pct double precision,
    load1 double precision,
    mem_pct double precision,
    swap_pct double precision,
    disk_max_pct double precision,
    temp_max_c double precision,
    net_rx_bps double precision,
    net_tx_bps double precision,
    failed_units integer,
    extras jsonb
);


--
-- Name: host_metric_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.host_metric_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: host_metric_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.host_metric_id_seq OWNED BY public.host_metric.id;


--
-- Name: hypothesis; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hypothesis (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    statement text NOT NULL,
    domain character varying(100) NOT NULL,
    confidence double precision DEFAULT 0.3,
    evidence_for jsonb DEFAULT '[]'::jsonb,
    evidence_against jsonb DEFAULT '[]'::jsonb,
    status character varying(50) DEFAULT 'active'::character varying,
    superseded_by character varying(36),
    times_useful integer DEFAULT 0,
    embedding public.vector(1024),
    first_formed timestamp with time zone DEFAULT now(),
    last_updated timestamp with time zone DEFAULT now(),
    last_evidence_at timestamp with time zone
);


--
-- Name: insight_mention_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insight_mention_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying NOT NULL,
    insight_id character varying NOT NULL,
    conversation_id character varying,
    mentioned_at timestamp with time zone DEFAULT now() NOT NULL,
    user_engaged boolean NOT NULL,
    engagement_type character varying,
    engaged_at timestamp with time zone
);


--
-- Name: insight_nudge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insight_nudge (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    insight_id character varying NOT NULL,
    delivery_method character varying NOT NULL,
    delivered_at timestamp without time zone DEFAULT now(),
    clicked boolean,
    dismissed_at timestamp without time zone,
    action_taken character varying
);


--
-- Name: intelligence_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intelligence_item (
    id character varying NOT NULL,
    source character varying NOT NULL,
    source_category character varying NOT NULL,
    title character varying NOT NULL,
    summary text,
    url character varying,
    full_content text,
    novelty_score double precision DEFAULT 0.5,
    relevance_score double precision DEFAULT 0.5,
    discovered_at timestamp without time zone DEFAULT now(),
    included_in_digest_at timestamp without time zone,
    notified_at timestamp without time zone,
    dismissed boolean DEFAULT false,
    digest_text text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: intelligence_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intelligence_report (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    report_type character varying NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    report_data json DEFAULT '{}'::json NOT NULL,
    summary text,
    insights json DEFAULT '[]'::json NOT NULL,
    patterns json DEFAULT '[]'::json NOT NULL,
    recommendations json DEFAULT '[]'::json NOT NULL,
    generation_time_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone
);


--
-- Name: intelligence_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.intelligence_report_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: intelligence_report_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.intelligence_report_id_seq OWNED BY public.intelligence_report.id;


--
-- Name: intelligence_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intelligence_reports (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    report_type character varying NOT NULL,
    report_date timestamp without time zone NOT NULL,
    title character varying NOT NULL,
    summary text NOT NULL,
    full_content text,
    key_insights text,
    metrics text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: intent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intent (
    intent_id character varying(255) NOT NULL,
    kind character varying(50) NOT NULL,
    origin character varying(20) NOT NULL,
    owner_user_id character varying(255) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    priority character varying(20),
    next_step text,
    evidence_refs jsonb DEFAULT '[]'::jsonb,
    permission_tier character varying(30),
    last_progress_at timestamp with time zone,
    next_review_at timestamp with time zone,
    outcome text,
    correlation_id character varying(64),
    source_table character varying(50),
    source_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: intent_edge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intent_edge (
    edge_id uuid DEFAULT gen_random_uuid() NOT NULL,
    from_intent_id character varying(255) NOT NULL,
    to_intent_id character varying(255) NOT NULL,
    relation character varying(30) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: interest_model; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.interest_model (
    user_id character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: interest_model_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.interest_model_version (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    version integer NOT NULL,
    content jsonb NOT NULL,
    changed_by character varying(50) NOT NULL,
    change_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ios_event_block; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ios_event_block (
    user_id character varying NOT NULL,
    ios_event_id character varying NOT NULL,
    ios_calendar_id character varying,
    title character varying,
    suppressed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: jarvis_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jarvis_tasks (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    kind public.taskkind NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    inputs jsonb,
    state public.taskstate NOT NULL,
    progress integer,
    estimated_duration_minutes integer,
    result jsonb,
    summary text,
    artifacts jsonb,
    audit_log jsonb,
    pending_confirmations jsonb,
    priority integer,
    timeout_minutes integer,
    retry_count integer,
    max_retries integer,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone,
    worker_id character varying(50),
    queue_name character varying(50)
);


--
-- Name: karma_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.karma_agents (
    agent_id character varying(50) NOT NULL,
    agent_type character varying(50) NOT NULL,
    display_name character varying(100),
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    is_active boolean DEFAULT true
);


--
-- Name: karma_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.karma_config (
    config_key character varying(100) NOT NULL,
    config_value jsonb NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: karma_dimensions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.karma_dimensions (
    dimension_id integer NOT NULL,
    agent_id character varying(50),
    dimension_name character varying(100) NOT NULL,
    description text,
    weight double precision DEFAULT 1.0
);


--
-- Name: karma_dimensions_dimension_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.karma_dimensions_dimension_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: karma_dimensions_dimension_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.karma_dimensions_dimension_id_seq OWNED BY public.karma_dimensions.dimension_id;


--
-- Name: karma_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.karma_scores (
    score_id integer NOT NULL,
    agent_id character varying(50),
    dimension_name character varying(100) NOT NULL,
    current_score double precision DEFAULT 50.0,
    trend double precision DEFAULT 0.0,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: karma_scores_score_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.karma_scores_score_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: karma_scores_score_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.karma_scores_score_id_seq OWNED BY public.karma_scores.score_id;


--
-- Name: known_domain; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.known_domain (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    domain_name character varying(255) NOT NULL,
    description text,
    proficiency character varying(50) DEFAULT 'intermediate'::character varying,
    key_concepts jsonb DEFAULT '[]'::jsonb,
    last_updated timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: known_place; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.known_place (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    place_type character varying(50) DEFAULT 'other'::character varying NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    radius_m integer DEFAULT 150 NOT NULL,
    source character varying(20) DEFAULT 'user'::character varying NOT NULL,
    visit_count integer DEFAULT 0 NOT NULL,
    last_seen_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL
);


--
-- Name: learning_artifact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_artifact (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    topic_id character varying(36),
    artifact_type character varying(50) NOT NULL,
    title character varying(255),
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: learning_blueprint; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_blueprint (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    subtitle character varying(255),
    description text,
    source_format character varying(50) DEFAULT 'text'::character varying,
    pace_mode character varying(50) DEFAULT 'self_directed'::character varying,
    status character varying(50) DEFAULT 'parsed'::character varying,
    import_confidence double precision DEFAULT 0.5,
    raw_text text NOT NULL,
    parsed_json jsonb DEFAULT '{}'::jsonb,
    materialized_at timestamp with time zone,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: learning_guide_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_guide_job (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    blueprint_id character varying(36) NOT NULL,
    status character varying(50) DEFAULT 'queued'::character varying,
    progress integer DEFAULT 0,
    current_step text,
    total_modules integer DEFAULT 0,
    completed_modules integer DEFAULT 0,
    artifacts_created integer DEFAULT 0,
    model character varying(255),
    error_message text,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    job_type character varying(50) DEFAULT 'guide'::character varying
);


--
-- Name: learning_progress; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_progress (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    topic_id character varying(36),
    source_id character varying(36),
    concept character varying(500),
    ease_factor double precision DEFAULT 2.5,
    interval_days integer DEFAULT 1,
    repetitions integer DEFAULT 0,
    next_review_at timestamp with time zone DEFAULT now(),
    last_reviewed_at timestamp with time zone,
    quality_history jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    review_mode character varying(50),
    review_mode_history jsonb DEFAULT '[]'::jsonb
);


--
-- Name: learning_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_session (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    topic_id character varying(36),
    started_at timestamp with time zone DEFAULT now(),
    ended_at timestamp with time zone,
    duration_minutes integer,
    session_type character varying(50),
    notes text,
    meta jsonb DEFAULT '{}'::jsonb
);


--
-- Name: learning_topic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_topic (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    parent_id character varying(36),
    title character varying(255) NOT NULL,
    description text,
    status character varying(50) DEFAULT 'active'::character varying,
    mastery_level double precision DEFAULT 0.0,
    priority integer DEFAULT 5,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    blueprint_id character varying(36)
);


--
-- Name: lesson_applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lesson_applications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lesson_id character varying(255),
    conversation_id character varying(255),
    message_id character varying(255),
    outcome character varying(20) DEFAULT 'unknown'::character varying,
    feedback_signal character varying(50),
    feedback_strength character varying(20),
    context_snippet text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: life_fact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.life_fact (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    predicate character varying(64) NOT NULL,
    value_text character varying(255) NOT NULL,
    weekday integer,
    source character varying(16) DEFAULT 'inferred'::character varying NOT NULL,
    authority integer DEFAULT 1 NOT NULL,
    confidence double precision DEFAULT 0.6 NOT NULL,
    evidence_count integer DEFAULT 1 NOT NULL,
    last_confirmed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: life_fact_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.life_fact_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: life_fact_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.life_fact_id_seq OWNED BY public.life_fact.id;


--
-- Name: list_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.list_item (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    list_name character varying(100) DEFAULT 'grocery'::character varying NOT NULL,
    item text NOT NULL,
    quantity character varying(100),
    checked boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    checked_at timestamp with time zone
);


--
-- Name: list_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.list_item_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: list_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.list_item_id_seq OWNED BY public.list_item.id;


--
-- Name: live_activity_registration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.live_activity_registration (
    id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    activity_id character varying(255) NOT NULL,
    logical_id character varying(255) NOT NULL,
    kind character varying(32) NOT NULL,
    push_token text NOT NULL,
    device_name character varying(255),
    environment character varying(16) DEFAULT 'production'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone
);


--
-- Name: location_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.location_event (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    accuracy double precision,
    place_id character varying,
    event_type character varying(10) NOT NULL,
    source character varying(30) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: location_trigger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.location_trigger (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    trigger_on character varying(10) NOT NULL,
    place_id character varying,
    latitude double precision,
    longitude double precision,
    radius_m integer,
    label character varying NOT NULL,
    reminder_title character varying NOT NULL,
    reminder_description text,
    recurring boolean DEFAULT false NOT NULL,
    cooldown_minutes integer DEFAULT 60 NOT NULL,
    status character varying(20) DEFAULT 'armed'::character varying NOT NULL,
    expires_at timestamp with time zone,
    last_fired_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: machine; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.machine (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    device_id character varying(255) NOT NULL,
    hostname character varying(255),
    platform character varying(50),
    os_version character varying(500),
    last_heartbeat_at timestamp with time zone,
    last_activity_at timestamp with time zone,
    activity_level character varying(20) DEFAULT 'idle'::character varying,
    is_online boolean DEFAULT false,
    capabilities jsonb,
    agent_version character varying(50),
    screenshot_enabled boolean DEFAULT true,
    screenshot_interval_seconds integer DEFAULT 30,
    clipboard_enabled boolean DEFAULT true,
    terminal_enabled boolean DEFAULT true,
    file_access_enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    keyboard_events_total integer DEFAULT 0,
    keyboard_events_recent integer DEFAULT 0,
    mouse_events_total integer DEFAULT 0,
    mouse_events_recent integer DEFAULT 0,
    active_window character varying,
    active_app character varying,
    friendly_name character varying
);


--
-- Name: managed_host; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.managed_host (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying(64) NOT NULL,
    hostname character varying(255) NOT NULL,
    username character varying(64) NOT NULL,
    port integer NOT NULL,
    ssh_key_path character varying(500) NOT NULL,
    description text,
    tags jsonb NOT NULL,
    last_inspection jsonb,
    last_status character varying(32),
    last_seen_at timestamp with time zone,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    transport character varying(16) DEFAULT 'ssh'::character varying NOT NULL,
    machine_id character varying(64),
    agent_token_hash character varying(64),
    agent_version character varying(16),
    agent_enrolled_at timestamp with time zone,
    agent_last_report_at timestamp with time zone,
    agent_snapshot jsonb,
    agent_alert_state jsonb
);


--
-- Name: maps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maps (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    map_data jsonb DEFAULT '{"edges": [], "nodes": []}'::jsonb,
    is_readonly boolean DEFAULT false,
    import_source character varying(50),
    import_raw text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: memory_edge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_edge (
    src character varying NOT NULL,
    dst character varying NOT NULL,
    type character varying NOT NULL,
    weight double precision,
    ts timestamp with time zone DEFAULT now()
);


--
-- Name: memory_embedding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_embedding (
    trace_id character varying NOT NULL,
    head character varying NOT NULL,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: memory_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_trace (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    content text NOT NULL,
    role character varying,
    created_at timestamp with time zone DEFAULT now(),
    salience double precision,
    source text,
    meta text
);


--
-- Name: ml_feature_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_feature_daily (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    feature_date date NOT NULL,
    focus_seconds_by_category jsonb,
    first_desktop_activity_at timestamp with time zone,
    last_desktop_activity_at timestamp with time zone,
    total_focus_seconds integer DEFAULT 0 NOT NULL,
    location_summary jsonb,
    sleep_hours double precision,
    hrv double precision,
    resting_heart_rate double precision,
    workout_logged boolean DEFAULT false NOT NULL,
    meals_logged integer DEFAULT 0 NOT NULL,
    total_calories double precision,
    calendar_event_count integer DEFAULT 0 NOT NULL,
    calendar_busy_seconds integer DEFAULT 0 NOT NULL,
    notifications_sent integer DEFAULT 0 NOT NULL,
    notifications_engaged integer DEFAULT 0 NOT NULL,
    voice_interactions integer DEFAULT 0 NOT NULL,
    voice_turns integer DEFAULT 0 NOT NULL,
    day_of_week integer,
    computed_at timestamp with time zone DEFAULT now()
);


--
-- Name: ml_model_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_model_version (
    id character varying NOT NULL,
    family character varying NOT NULL,
    version character varying NOT NULL,
    artifact_key character varying,
    metrics jsonb,
    metadata_json jsonb,
    status character varying DEFAULT 'candidate'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    activated_at timestamp with time zone
);


--
-- Name: ml_notification_outcome; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_notification_outcome (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    notification_log_id character varying,
    sent_at timestamp with time zone NOT NULL,
    hour integer,
    day_of_week integer,
    activity_state character varying,
    interruptibility_score double precision,
    device character varying,
    category character varying,
    location character varying,
    outcome character varying,
    outcome_latency_seconds double precision,
    features jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: ml_prediction_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_prediction_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    model_family character varying NOT NULL,
    model_version character varying NOT NULL,
    features_hash character varying,
    features jsonb,
    prediction jsonb,
    ground_truth jsonb,
    mode character varying DEFAULT 'shadow'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: models_3d; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.models_3d (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    filename character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    file_format character varying(20) NOT NULL,
    minio_key character varying(512) NOT NULL,
    file_size bigint DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: moment_card; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.moment_card (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    kind character varying(30) NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    source_ref text,
    source_kind character varying(30),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    seen_at timestamp with time zone,
    dismissed_at timestamp with time zone,
    CONSTRAINT moment_card_kind_check CHECK (((kind)::text = ANY ((ARRAY['proof_of_memory'::character varying, 'artifact_unwrap'::character varying])::text[])))
);


--
-- Name: morning_brief; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.morning_brief (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    brief_date date NOT NULL,
    news_summary text,
    weather_summary text,
    calendar_summary text,
    full_text text,
    audio_path character varying,
    audio_duration_seconds double precision,
    recovery_text text,
    recovery_audio_path character varying,
    news_sources jsonb,
    weather_data jsonb,
    calendar_events jsonb,
    generated_at timestamp with time zone,
    ntfy_sent_at timestamp with time zone,
    viewed_at timestamp with time zone,
    listened_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: morning_readiness; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.morning_readiness (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    hrv_ms integer,
    rhr integer,
    sleep_hours integer,
    energy integer NOT NULL,
    soreness integer NOT NULL,
    stress integer NOT NULL,
    time_available_min integer NOT NULL,
    score integer NOT NULL,
    recommendation character varying NOT NULL,
    adjustments json,
    message text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: note; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.note (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    folder_id character varying,
    title character varying,
    content text NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    embedding public.vector(1024),
    starred boolean DEFAULT false NOT NULL,
    tags json DEFAULT '[]'::json NOT NULL
);


--
-- Name: note_connection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.note_connection (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    source_note_id character varying NOT NULL,
    target_note_id character varying NOT NULL,
    connection_type character varying NOT NULL,
    strength integer,
    auto_generated character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: notification_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_log (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    sent_at timestamp with time zone DEFAULT now() NOT NULL,
    topic character varying(200) NOT NULL,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    title character varying(500),
    message text,
    priority character varying(20) DEFAULT 'normal'::character varying,
    source character varying(50) DEFAULT 'unified_heartbeat'::character varying,
    agent_run_id integer,
    cooldown_hours double precision DEFAULT 4.0,
    sent boolean DEFAULT true,
    dedup_blocked boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    outbox_item_id uuid,
    read_at timestamp with time zone,
    engaged boolean DEFAULT false,
    dismissed_at timestamp with time zone,
    response_text text,
    blocked_count integer DEFAULT 1 NOT NULL,
    suppress_reason character varying(40)
);


--
-- Name: notification_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notification_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notification_log_id_seq OWNED BY public.notification_log.id;


--
-- Name: notification_preference; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_preference (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    category character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    custom_ban_phrases jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: notification_preference_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notification_preference_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_preference_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notification_preference_id_seq OWNED BY public.notification_preference.id;


--
-- Name: notification_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_queue (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    title character varying(500) NOT NULL,
    message text,
    urgency character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    topic character varying(500),
    source character varying(100) DEFAULT 'system'::character varying,
    queued_at timestamp with time zone DEFAULT now() NOT NULL,
    deliver_by timestamp with time zone,
    delivered_at timestamp with time zone,
    was_delivered boolean DEFAULT false,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: notification_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notification_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notification_queue_id_seq OWNED BY public.notification_queue.id;


--
-- Name: outbound_intent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbound_intent (
    outbound_intent_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    subject text NOT NULL,
    facts jsonb DEFAULT '[]'::jsonb NOT NULL,
    why_now text,
    desired_response text,
    confidence real DEFAULT 1.0 NOT NULL,
    interruption_cost real,
    channel_eligibility jsonb DEFAULT '[]'::jsonb NOT NULL,
    dedupe_key character varying(255),
    source_intent_id character varying(255),
    correlation_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: outbox_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_item (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    title text NOT NULL,
    body text,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    source character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'new'::character varying NOT NULL,
    dedupe_key character varying(255),
    payload jsonb DEFAULT '{}'::jsonb,
    action_history jsonb DEFAULT '[]'::jsonb,
    batch_id character varying(36),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    archived_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: outbox_usage_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_usage_log (
    id bigint NOT NULL,
    kind character varying(10) NOT NULL,
    surface character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT outbox_usage_log_kind_check CHECK (((kind)::text = ANY ((ARRAY['read'::character varying, 'write'::character varying])::text[])))
);


--
-- Name: outbox_usage_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.outbox_usage_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: outbox_usage_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.outbox_usage_log_id_seq OWNED BY public.outbox_usage_log.id;


--
-- Name: pattern_discovery_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pattern_discovery_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(36) NOT NULL,
    run_type character varying(50) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    status character varying(20) NOT NULL,
    bins_created integer,
    bins_updated integer,
    patterns_discovered integer,
    patterns_validated integer,
    patterns_invalidated integer,
    lookback_days integer,
    domain_pairs_analyzed jsonb,
    error_message text,
    error_details jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: pattern_suggestion_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pattern_suggestion_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    pattern_id uuid,
    user_id character varying(255) NOT NULL,
    trigger_context jsonb,
    message_sent text,
    outcome character varying(20),
    user_response text,
    action_taken boolean DEFAULT false,
    suggested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    responded_at timestamp without time zone,
    expires_at timestamp without time zone
);


--
-- Name: person; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    canonical_name character varying(255) NOT NULL,
    emails jsonb DEFAULT '[]'::jsonb NOT NULL,
    aliases jsonb DEFAULT '[]'::jsonb NOT NULL,
    pkg_person_ref character varying,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_interaction_at timestamp with time zone,
    last_interaction_kind character varying(32),
    interaction_count integer DEFAULT 0 NOT NULL,
    mention_count integer DEFAULT 0 NOT NULL,
    importance double precision DEFAULT 0.5 NOT NULL,
    is_vip boolean DEFAULT false NOT NULL,
    muted boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pkg_embedding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pkg_embedding (
    pkg_id character varying NOT NULL,
    node_type character varying NOT NULL,
    content_text text NOT NULL,
    embedding public.vector(1024),
    confidence double precision DEFAULT 0.7,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: plan_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plan_templates (
    id character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    template_type character varying NOT NULL,
    days_per_week integer NOT NULL,
    weeks_per_phase integer,
    phases json NOT NULL,
    equipment_required json,
    difficulty_level integer,
    primary_goals json,
    workout_templates json NOT NULL,
    substitution_rules json,
    progression_rules json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: pr_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_task_link (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    pr_id character varying NOT NULL,
    task_id character varying NOT NULL,
    auto_linked boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: prediction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prediction (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    statement text NOT NULL,
    domain character varying(100),
    confidence double precision NOT NULL,
    source_episode_id character varying(36),
    outcome character varying(50),
    resolved_at timestamp with time zone,
    resolution_notes text,
    created_at timestamp with time zone DEFAULT now(),
    user_id character varying,
    prediction_key character varying,
    source character varying,
    window_start timestamp with time zone,
    window_end timestamp with time zone,
    predicted_value jsonb,
    matched_value jsonb,
    salience_emitted boolean DEFAULT false NOT NULL
);


--
-- Name: presence_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.presence_log (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    activity_type character varying(50) NOT NULL,
    platform character varying(20),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: privacy_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.privacy_settings (
    user_id character varying NOT NULL,
    memory_retention_days integer DEFAULT 365,
    share_reflections_with_ai boolean DEFAULT true,
    autonomous_level character varying(20) DEFAULT 'auto'::character varying,
    data_categories jsonb DEFAULT '{}'::jsonb,
    export_enabled boolean DEFAULT true,
    analytics_enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: progress_photo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.progress_photo (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    storage_key character varying(500) NOT NULL,
    thumbnail_key character varying(500),
    original_filename character varying(500),
    mime_type character varying(100),
    file_size integer,
    width integer,
    height integer,
    taken_at timestamp with time zone,
    notes text,
    bodyweight double precision,
    bodyweight_unit character varying(8) DEFAULT 'lbs'::character varying,
    critique text,
    critique_model character varying(100),
    critiqued_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    auto_detected boolean DEFAULT false,
    status character varying DEFAULT 'active'::character varying,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    tags text[],
    metadata jsonb
);


--
-- Name: TABLE project; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.project IS 'Auto-detected or manual projects';


--
-- Name: project_entity_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_entity_link (
    project_id character varying NOT NULL,
    entity_type character varying NOT NULL,
    entity_id character varying NOT NULL,
    relevance_score double precision DEFAULT 1.0,
    added_at timestamp with time zone DEFAULT now()
);


--
-- Name: project_file; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_file (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    user_id character varying NOT NULL,
    folder_id character varying,
    filename character varying(500) NOT NULL,
    storage_key character varying(1000) NOT NULL,
    mime_type character varying(100),
    file_size integer NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: project_folder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_folder (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying(255) NOT NULL,
    parent_id character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: promotion_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.promotion_event (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    domain character varying NOT NULL,
    context character varying NOT NULL,
    signal_key character varying,
    signal_ref character varying,
    significance double precision,
    threshold_at_time double precision,
    reason character varying,
    promoted boolean DEFAULT false,
    surfaced_as character varying,
    notification_id character varying,
    description text,
    outcome character varying,
    outcome_at timestamp with time zone,
    engaged boolean,
    meta jsonb DEFAULT '{}'::jsonb
);


--
-- Name: prompt_proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompt_proposals (
    proposal_id integer NOT NULL,
    target_agent character varying(50) NOT NULL,
    target_prompt_section character varying(100),
    current_content text,
    proposed_content text,
    reasoning text NOT NULL,
    supporting_pattern_ids text[],
    expected_improvement text,
    status character varying(20) DEFAULT 'pending'::character varying,
    reviewed_by character varying(50),
    reviewed_at timestamp without time zone,
    review_notes text,
    implemented_at timestamp without time zone,
    outcome_assessment text,
    outcome_karma_delta double precision,
    karma_state_at_proposal jsonb,
    karma_state_at_implementation jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: prompt_proposals_proposal_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prompt_proposals_proposal_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prompt_proposals_proposal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prompt_proposals_proposal_id_seq OWNED BY public.prompt_proposals.proposal_id;


--
-- Name: prompt_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompt_versions (
    version_id integer NOT NULL,
    agent character varying(50) NOT NULL,
    section character varying(100) NOT NULL,
    content text NOT NULL,
    reason text,
    proposal_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(50) DEFAULT 'system'::character varying
);


--
-- Name: prompt_versions_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prompt_versions_version_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prompt_versions_version_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prompt_versions_version_id_seq OWNED BY public.prompt_versions.version_id;


--
-- Name: proxmox_container; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proxmox_container (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    vmid integer NOT NULL,
    user_id character varying NOT NULL,
    session_id character varying,
    hostname character varying(100) NOT NULL,
    ip_address character varying(45),
    preset character varying(30) NOT NULL,
    cores integer NOT NULL,
    memory_mb integer NOT NULL,
    disk_gb integer NOT NULL,
    persistent boolean DEFAULT false,
    purpose text,
    status character varying(20) DEFAULT 'creating'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    destroyed_at timestamp with time zone,
    last_used_at timestamp with time zone DEFAULT now()
);


--
-- Name: pull_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pull_request (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    pr_number integer NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    source_branch character varying(255),
    target_branch character varying(255),
    author character varying(255),
    opened_at timestamp with time zone,
    closed_at timestamp with time zone,
    merged_at timestamp with time zone,
    raw_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: push_token; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_token (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    token character varying NOT NULL,
    platform character varying NOT NULL,
    device_name character varying,
    is_active boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: qa_checklist_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_checklist_item (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    user_id character varying NOT NULL,
    label character varying(255) NOT NULL,
    sort_order integer DEFAULT 0,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: qa_commit_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_commit_result (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    commit_id character varying NOT NULL,
    project_id character varying NOT NULL,
    user_id character varying NOT NULL,
    checked_items jsonb DEFAULT '[]'::jsonb,
    notes text,
    status character varying(20) DEFAULT 'pending'::character varying,
    tested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: raw_buffer_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.raw_buffer_stats (
    id integer NOT NULL,
    stream_type character varying(50) NOT NULL,
    window_start timestamp without time zone NOT NULL,
    window_end timestamp without time zone NOT NULL,
    entries_count integer DEFAULT 0 NOT NULL,
    processed_count integer DEFAULT 0 NOT NULL,
    discarded_count integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: raw_buffer_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.raw_buffer_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: raw_buffer_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.raw_buffer_stats_id_seq OWNED BY public.raw_buffer_stats.id;


--
-- Name: readiness_adjustments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.readiness_adjustments (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    readiness_id character varying NOT NULL,
    workout_id character varying NOT NULL,
    adjustment_type character varying NOT NULL,
    original_prescription json,
    adjusted_prescription json,
    reasoning text,
    applied_at timestamp with time zone DEFAULT now()
);


--
-- Name: readiness_baselines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.readiness_baselines (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    hrv_baseline double precision,
    hrv_std_dev double precision,
    rhr_baseline double precision,
    rhr_std_dev double precision,
    sleep_baseline double precision,
    baseline_period_days integer,
    last_calculated timestamp without time zone,
    sample_count integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: reasoning_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reasoning_trace (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    episode_id character varying(36),
    conversation_id character varying(36),
    thinking_content text NOT NULL,
    reasoning_effort character varying(20),
    tool_calls_made jsonb DEFAULT '[]'::jsonb,
    final_answer_summary text,
    token_count integer,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: recipe; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recipe (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    category character varying,
    ingredients json NOT NULL,
    instructions text NOT NULL,
    prep_time_minutes integer,
    servings integer DEFAULT 1 NOT NULL,
    calories numeric(8,2),
    protein numeric(8,2),
    carbs numeric(8,2),
    fats numeric(8,2),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    cook_time_minutes integer,
    meal_type text,
    cuisine text,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_url text,
    source_name text,
    recipe_notes text DEFAULT ''::text,
    starred boolean DEFAULT false NOT NULL,
    rating integer,
    last_made_at timestamp with time zone,
    times_made integer DEFAULT 0 NOT NULL,
    embedding public.vector(1024),
    macros_estimated boolean DEFAULT false NOT NULL
);


--
-- Name: reflection_hypotheses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reflection_hypotheses (
    hypothesis_id integer NOT NULL,
    hypothesis text NOT NULL,
    supporting_evidence jsonb DEFAULT '[]'::jsonb,
    contradicting_evidence jsonb DEFAULT '[]'::jsonb,
    confidence double precision DEFAULT 0.5,
    test_criteria text,
    test_deadline timestamp without time zone,
    status character varying(20) DEFAULT 'testing'::character varying,
    outcome text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: reflection_hypotheses_hypothesis_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reflection_hypotheses_hypothesis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reflection_hypotheses_hypothesis_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reflection_hypotheses_hypothesis_id_seq OWNED BY public.reflection_hypotheses.hypothesis_id;


--
-- Name: reflection_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reflection_observations (
    observation_id integer NOT NULL,
    observation_type character varying(50) NOT NULL,
    subject_agent character varying(50),
    subject_dimension character varying(100),
    summary text NOT NULL,
    details jsonb,
    confidence double precision DEFAULT 0.5,
    evidence_refs jsonb,
    pattern_id character varying(100),
    resolved boolean DEFAULT false,
    resolution text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp without time zone
);


--
-- Name: reflection_observations_observation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reflection_observations_observation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reflection_observations_observation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reflection_observations_observation_id_seq OWNED BY public.reflection_observations.observation_id;


--
-- Name: reflection_patterns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reflection_patterns (
    pattern_id character varying(100) NOT NULL,
    pattern_type character varying(50) NOT NULL,
    description text NOT NULL,
    affected_agent character varying(50),
    affected_dimension character varying(100),
    observation_count integer DEFAULT 1,
    first_observed timestamp without time zone,
    last_observed timestamp without time zone,
    confidence double precision DEFAULT 0.5,
    status character varying(20) DEFAULT 'active'::character varying,
    proposed_action text,
    action_taken text,
    metadata jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: reflection_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reflection_settings (
    user_id character varying NOT NULL,
    preferred_time time without time zone DEFAULT '21:00:00'::time without time zone,
    timezone character varying(50) DEFAULT 'UTC'::character varying,
    enabled boolean DEFAULT true,
    quiet_hours jsonb DEFAULT '{}'::jsonb,
    reminder_channels jsonb DEFAULT '{}'::jsonb,
    streak_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: registered_endpoint; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registered_endpoint (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    base_url character varying(500) NOT NULL,
    auth_type character varying(20) DEFAULT 'none'::character varying NOT NULL,
    auth_header character varying(100),
    auth_secret_env character varying(100),
    rate_limit_per_minute integer DEFAULT 60,
    allowed_paths jsonb DEFAULT '[]'::jsonb,
    allowed_methods jsonb DEFAULT '["GET"]'::jsonb,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: registered_endpoint_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.registered_endpoint_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: registered_endpoint_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.registered_endpoint_id_seq OWNED BY public.registered_endpoint.id;


--
-- Name: relationship_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.relationship_state (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    phase character varying(50) DEFAULT 'early'::character varying,
    total_conversations integer DEFAULT 0,
    total_episodes integer DEFAULT 0,
    first_interaction timestamp with time zone,
    topics_discussed jsonb DEFAULT '{}'::jsonb,
    shared_references jsonb DEFAULT '[]'::jsonb,
    trust_signals jsonb DEFAULT '[]'::jsonb,
    tension_events jsonb DEFAULT '[]'::jsonb,
    communication_preferences jsonb DEFAULT '{}'::jsonb,
    last_updated timestamp with time zone DEFAULT now()
);


--
-- Name: reminder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reminder (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    description text,
    reminder_time timestamp without time zone NOT NULL,
    is_completed boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    event_id character varying
);


--
-- Name: research_brief; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_brief (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    brief_date character varying(10) NOT NULL,
    full_text text,
    audio_path text,
    audio_duration_seconds double precision,
    sources jsonb,
    paper_count integer,
    generated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: research_brief_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.research_brief_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_brief_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.research_brief_id_seq OWNED BY public.research_brief.id;


--
-- Name: research_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_job (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    report_id character varying(36),
    status character varying(50) DEFAULT 'queued'::character varying,
    progress integer DEFAULT 0,
    current_step text,
    search_queries jsonb DEFAULT '[]'::jsonb,
    sources_found integer DEFAULT 0,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: research_message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_message (
    id character varying NOT NULL,
    plan_id character varying NOT NULL,
    direction character varying NOT NULL,
    content text NOT NULL,
    step_index integer,
    status character varying DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    answered_at timestamp without time zone
);


--
-- Name: research_plan; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_plan (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    objective text NOT NULL,
    steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying DEFAULT 'draft'::character varying NOT NULL,
    created_by character varying DEFAULT 'sara'::character varying NOT NULL,
    current_step_index integer DEFAULT 0,
    findings_summary text,
    model_id character varying,
    container_vmid integer,
    total_tokens_used integer DEFAULT 0,
    error_log text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    origin character varying(32) DEFAULT 'sara_internal'::character varying NOT NULL,
    celery_task_id character varying(64)
);


--
-- Name: research_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_report (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying(36) NOT NULL,
    topic_id character varying(36),
    question text NOT NULL,
    summary text,
    full_content text,
    confidence double precision,
    novelty_score double precision,
    sources_used jsonb DEFAULT '[]'::jsonb,
    report_type character varying(50) DEFAULT 'quick'::character varying,
    status character varying(50) DEFAULT 'pending'::character varying,
    store_in_knowledge boolean DEFAULT false,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


--
-- Name: sara_activity_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_activity_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    kind character varying(32) NOT NULL,
    summary text NOT NULL,
    body text,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    embedding public.vector(1024),
    audience character varying(16),
    dedup_key character varying(200)
);


--
-- Name: sara_commitment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_commitment (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    text text NOT NULL,
    created_from character varying(100) NOT NULL,
    trigger_at timestamp with time zone,
    trigger_description text,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    closure_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    CONSTRAINT ck_sara_commitment_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'done'::character varying, 'dropped'::character varying])::text[])))
);


--
-- Name: sara_daemon_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_daemon_state (
    id character varying(32) NOT NULL,
    version character varying(64) DEFAULT '0.0.0'::character varying NOT NULL,
    state character varying(32) DEFAULT 'boot'::character varying NOT NULL,
    pid integer,
    hostname character varying(128),
    started_at timestamp with time zone,
    last_heartbeat_at timestamp with time zone,
    last_tick_summary text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_delta_served_at timestamp with time zone,
    CONSTRAINT sara_daemon_state_singleton CHECK (((id)::text = 'singleton'::text))
);


--
-- Name: sara_focus; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_focus (
    id character varying(32) NOT NULL,
    topic text,
    why text,
    set_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT sara_focus_singleton CHECK (((id)::text = 'singleton'::text))
);


--
-- Name: sara_goal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_goal (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    why text,
    created_by character varying(32) DEFAULT 'sara'::character varying NOT NULL,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    plan jsonb DEFAULT '[]'::jsonb NOT NULL,
    progress jsonb DEFAULT '[]'::jsonb NOT NULL,
    artifacts jsonb DEFAULT '[]'::jsonb NOT NULL,
    outcome text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_progress_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: sara_inbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_inbox (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(64) DEFAULT 'david_api'::character varying NOT NULL,
    urgency character varying(16) DEFAULT 'normal'::character varying NOT NULL,
    prompt text NOT NULL,
    context text,
    status character varying(16) DEFAULT 'queued'::character varying NOT NULL,
    picked_up_at timestamp with time zone,
    completed_at timestamp with time zone,
    completion_summary text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT sara_inbox_status_valid CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'in_progress'::character varying, 'done'::character varying, 'dismissed'::character varying])::text[]))),
    CONSTRAINT sara_inbox_urgency_valid CHECK (((urgency)::text = ANY ((ARRAY['low'::character varying, 'normal'::character varying, 'high'::character varying])::text[])))
);


--
-- Name: sara_interest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_interest (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    topic text NOT NULL,
    display_name text NOT NULL,
    why text,
    weight double precision DEFAULT '1'::double precision NOT NULL,
    last_acted_at timestamp with time zone,
    last_updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source character varying(32) DEFAULT 'reflection'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    embedding public.vector(1024),
    blocked boolean DEFAULT false NOT NULL,
    strikes integer DEFAULT 0 NOT NULL,
    last_reaction_at timestamp with time zone,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    CONSTRAINT sara_interest_source_valid CHECK (((source)::text = ANY ((ARRAY['reflection'::character varying, 'external_event'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT sara_interest_status_valid CHECK (((status)::text = ANY ((ARRAY['noticed'::character varying, 'candidate'::character varying, 'aligned'::character varying, 'proposed'::character varying, 'discussing'::character varying, 'approved'::character varying, 'deferred'::character varying, 'rejected'::character varying, 'active'::character varying, 'blocked'::character varying, 'completed'::character varying, 'abandoned'::character varying])::text[]))),
    CONSTRAINT sara_interest_weight_nonneg CHECK ((weight >= (0.0)::double precision))
);


--
-- Name: sara_journal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_journal (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    entry_type character varying(50) DEFAULT 'periodic'::character varying NOT NULL,
    content text NOT NULL,
    context jsonb,
    observations text,
    interpretation text,
    emotional_state character varying(100),
    actions_taken text,
    watching_for text,
    conversation_id character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: sara_presence_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_presence_snapshot (
    user_id character varying NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    revision bigint DEFAULT '0'::bigint NOT NULL,
    state character varying(24) DEFAULT 'resting'::character varying NOT NULL,
    headline text DEFAULT 'Available'::text NOT NULL,
    detail text,
    source character varying(128) DEFAULT 'world_state'::character varying NOT NULL,
    correlation_id character varying(128),
    event_id character varying(36),
    task_id character varying(255),
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    valid_until timestamp with time zone NOT NULL
);


--
-- Name: sara_reflection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_reflection (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    reflection_type character varying(50) NOT NULL,
    domain character varying(100),
    content text NOT NULL,
    source_episodes jsonb DEFAULT '[]'::jsonb,
    confidence double precision DEFAULT 0.5,
    times_applied integer DEFAULT 0,
    effectiveness_score double precision,
    superseded_by character varying(36),
    is_active boolean DEFAULT true,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_applied_at timestamp without time zone,
    trigger_context jsonb
);


--
-- Name: sara_soul; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_soul (
    id integer NOT NULL,
    section character varying(50) NOT NULL,
    content text NOT NULL,
    version integer DEFAULT 1,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by character varying(50) NOT NULL
);


--
-- Name: sara_soul_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sara_soul_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sara_soul_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sara_soul_id_seq OWNED BY public.sara_soul.id;


--
-- Name: sara_tool; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_tool (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(64) NOT NULL,
    description text NOT NULL,
    args_schema jsonb NOT NULL,
    active_version_id uuid,
    enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT sara_tool_name_format CHECK (((name)::text ~ '^[a-z][a-z0-9_]{2,63}$'::text))
);


--
-- Name: sara_tool_invocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_tool_invocation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tool_id uuid NOT NULL,
    version_id uuid NOT NULL,
    args jsonb NOT NULL,
    result jsonb,
    error text,
    duration_ms integer,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: sara_tool_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sara_tool_version (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tool_id uuid NOT NULL,
    version integer NOT NULL,
    code text NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: saved_meal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.saved_meal (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    name character varying(200) NOT NULL,
    default_meal_type character varying(20),
    items jsonb DEFAULT '[]'::jsonb NOT NULL,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: say_candidate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.say_candidate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source character varying(100) NOT NULL,
    kind character varying(20) NOT NULL,
    topic_entities text[] DEFAULT '{}'::text[] NOT NULL,
    summary text NOT NULL,
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    value_guess double precision,
    valid_until timestamp with time zone NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    judge_reason text,
    utterance_id uuid,
    CONSTRAINT ck_say_candidate_kind CHECK (((kind)::text = ANY ((ARRAY['inform'::character varying, 'followup'::character varying, 'prep'::character varying, 'alert'::character varying, 'retrospective'::character varying])::text[]))),
    CONSTRAINT ck_say_candidate_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'judged_send'::character varying, 'judged_batch'::character varying, 'judged_drop'::character varying, 'expired'::character varying, 'composed'::character varying, 'declined'::character varying])::text[])))
);


--
-- Name: scheduled_home_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_home_action (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    entity_id character varying(255) NOT NULL,
    domain character varying(50) NOT NULL,
    action character varying(50) NOT NULL,
    parameters json,
    scheduled_at timestamp with time zone NOT NULL,
    executed_at timestamp with time zone,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error_message text,
    description character varying(500),
    recurring boolean DEFAULT false NOT NULL,
    recurrence_pattern character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scheduled_home_action_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduled_home_action_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduled_home_action_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduled_home_action_id_seq OWNED BY public.scheduled_home_action.id;


--
-- Name: scheduled_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_job (
    key character varying(100) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    task_name character varying(255) NOT NULL,
    schedule_kind character varying(20) NOT NULL,
    cron_expr character varying(255),
    interval_seconds integer,
    timezone character varying(64) DEFAULT 'America/New_York'::character varying NOT NULL,
    args jsonb DEFAULT '[]'::jsonb NOT NULL,
    kwargs jsonb DEFAULT '{}'::jsonb NOT NULL,
    queue character varying(50),
    expires_seconds integer,
    enabled boolean DEFAULT true NOT NULL,
    editable boolean DEFAULT true NOT NULL,
    source character varying(20) DEFAULT 'system'::character varying NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    last_status character varying(20),
    last_error text,
    last_run_duration_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    visibility character varying(20) DEFAULT 'system'::character varying NOT NULL,
    singular_class character varying(30),
    CONSTRAINT ck_scheduled_job_schedule_consistent CHECK (((((schedule_kind)::text = 'cron'::text) AND (cron_expr IS NOT NULL)) OR (((schedule_kind)::text = 'interval'::text) AND (interval_seconds IS NOT NULL))))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    name text NOT NULL,
    applied_at timestamp without time zone DEFAULT now()
);


--
-- Name: scratchpad_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scratchpad_entry (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    content text NOT NULL,
    category character varying(32) DEFAULT 'other'::character varying NOT NULL,
    active_until timestamp with time zone,
    created_from character varying(32) DEFAULT 'chat'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    cleared boolean DEFAULT false NOT NULL
);


--
-- Name: scratchpad_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scratchpad_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scratchpad_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scratchpad_entry_id_seq OWNED BY public.scratchpad_entry.id;


--
-- Name: semantic_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.semantic_summary (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    scope character varying NOT NULL,
    summary text NOT NULL,
    embedding public.vector(1024) NOT NULL,
    coverage jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: shadow_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_event (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    session_id character varying NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    event_type character varying NOT NULL,
    app_name character varying,
    metadata jsonb,
    classified_as character varying,
    tags jsonb DEFAULT '[]'::jsonb,
    screenshot_id character varying(36),
    content_hash character varying(64)
);


--
-- Name: shadow_note; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_note (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    session_id character varying NOT NULL,
    note_type character varying NOT NULL,
    content text NOT NULL,
    source character varying DEFAULT 'chat'::character varying,
    due_date timestamp with time zone,
    priority character varying,
    "timestamp" timestamp with time zone DEFAULT now()
);


--
-- Name: shadow_screenshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_screenshot (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    minio_key character varying(500) NOT NULL,
    file_size_bytes integer,
    "timestamp" timestamp with time zone DEFAULT now(),
    window_title character varying(500),
    app_name character varying(100),
    image_hash character varying(64),
    was_blurred boolean DEFAULT false,
    blur_reason character varying(100),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: shadow_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_session (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id character varying NOT NULL,
    device_id character varying,
    status character varying DEFAULT 'active'::character varying,
    duration_minutes integer,
    privacy_mode boolean DEFAULT false,
    started_at timestamp with time zone DEFAULT now(),
    paused_at timestamp with time zone,
    resumed_at timestamp with time zone,
    ended_at timestamp with time zone,
    context character varying,
    calendar_event_id character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    machine_id character varying(36),
    target_machine character varying(50),
    screenshots_enabled boolean DEFAULT true,
    screenshot_interval_seconds integer DEFAULT 30,
    clipboard_enabled boolean DEFAULT true,
    terminal_enabled boolean DEFAULT true,
    file_access_enabled boolean DEFAULT true
);


--
-- Name: shadow_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_summary (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    session_id character varying NOT NULL,
    decisions jsonb DEFAULT '[]'::jsonb,
    tasks jsonb DEFAULT '[]'::jsonb,
    questions jsonb DEFAULT '[]'::jsonb,
    ideas jsonb DEFAULT '[]'::jsonb,
    refs jsonb DEFAULT '[]'::jsonb,
    timeline jsonb DEFAULT '[]'::jsonb,
    changeset jsonb DEFAULT '{}'::jsonb,
    full_text text,
    committed boolean DEFAULT false,
    committed_note_id character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: shared_content; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shared_content (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    content_type character varying(30) NOT NULL,
    original_url text,
    title character varying(500),
    description text,
    thumbnail_url text,
    extracted_text text,
    extraction_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    extraction_error text,
    word_count integer,
    storage_key character varying(500),
    original_filename character varying(500),
    mime_type character varying(100),
    file_size integer,
    meta jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'unread'::character varying NOT NULL,
    read_at timestamp with time zone,
    decided_at timestamp with time zone,
    discussed boolean DEFAULT false,
    consolidated boolean DEFAULT false,
    consolidated_at timestamp with time zone,
    episode_id character varying,
    embedding public.vector(1024),
    shared_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: signal_baseline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_baseline (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    domain character varying NOT NULL,
    signal_key character varying NOT NULL,
    ewma double precision,
    ewmvar double precision,
    last_value double precision,
    sample_count bigint DEFAULT 0,
    event_rate_per_hr double precision,
    last_observed_at timestamp with time zone,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: singular_context_turn_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.singular_context_turn_log (
    id bigint NOT NULL,
    user_id character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: singular_context_turn_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.singular_context_turn_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: singular_context_turn_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.singular_context_turn_log_id_seq OWNED BY public.singular_context_turn_log.id;


--
-- Name: soul_change_proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.soul_change_proposals (
    id integer NOT NULL,
    section character varying(50) NOT NULL,
    current_content text,
    proposed_content text NOT NULL,
    rationale text NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying,
    rejection_reason text,
    proposed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    resolved_at timestamp with time zone,
    resolved_by character varying(50),
    source_ref character varying(128),
    kind character varying(20) DEFAULT 'identity'::character varying NOT NULL,
    evidence_count integer
);


--
-- Name: soul_change_proposals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.soul_change_proposals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: soul_change_proposals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.soul_change_proposals_id_seq OWNED BY public.soul_change_proposals.id;


--
-- Name: source_chunk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_chunk (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    source_id character varying(36) NOT NULL,
    chunk_idx integer NOT NULL,
    text text NOT NULL,
    breadcrumb character varying(500),
    embedding public.vector(1024) NOT NULL,
    concept_tags jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    analogy_version jsonb,
    chapter_ref character varying(500),
    page_start integer
);


--
-- Name: standing_order; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.standing_order (
    id integer NOT NULL,
    user_id character varying(255) NOT NULL,
    description text NOT NULL,
    trigger_type character varying(50) NOT NULL,
    trigger_config jsonb DEFAULT '{}'::jsonb,
    action_type character varying(50) NOT NULL,
    action_config jsonb DEFAULT '{}'::jsonb,
    source character varying(50) DEFAULT 'user'::character varying,
    pattern_id character varying,
    status character varying(20) DEFAULT 'active'::character varying,
    last_executed_at timestamp with time zone,
    execution_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    condition jsonb
);


--
-- Name: standing_order_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.standing_order_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: standing_order_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.standing_order_id_seq OWNED BY public.standing_order.id;


--
-- Name: stimulus_habituation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stimulus_habituation (
    id integer NOT NULL,
    generator character varying(80) NOT NULL,
    stimulus_key character varying(255) NOT NULL,
    strength double precision DEFAULT '1'::double precision NOT NULL,
    last_fired_at timestamp with time zone,
    last_engaged_at timestamp with time zone,
    last_decay_checked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stimulus_habituation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.stimulus_habituation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stimulus_habituation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.stimulus_habituation_id_seq OWNED BY public.stimulus_habituation.id;


--
-- Name: subconscious_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subconscious_log (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    snapshot_at timestamp with time zone NOT NULL,
    state_snapshot jsonb NOT NULL,
    nudges_generated jsonb,
    signals_processed jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: subconscious_nudge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subconscious_nudge (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    nudge_type character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    action_suggestion text,
    delivery_channel character varying(50) NOT NULL,
    delivered_at timestamp with time zone,
    acknowledged_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: subconscious_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subconscious_state (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    last_meal_type character varying(20),
    last_meal_at timestamp with time zone,
    hours_since_meal double precision,
    typical_meal_windows jsonb,
    inferred_energy_level double precision,
    inferred_mood character varying(50),
    message_velocity double precision,
    message_sentiment_avg double precision,
    current_focus_areas jsonb,
    active_threads jsonb,
    last_sleep_hours double precision,
    last_sleep_quality character varying(20),
    sleep_deficit_hours double precision,
    docker_health jsonb,
    service_health jsonb,
    llm_primary_status character varying(20),
    llm_failover_status character varying(20),
    llm_active_backend character varying(100),
    last_presence_at timestamp with time zone,
    hours_since_presence double precision,
    is_waking_hours boolean,
    updated_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    first_activity_today timestamp with time zone,
    last_activity_at timestamp with time zone,
    has_chatted_today boolean DEFAULT false,
    hours_since_wakeup double precision,
    is_past_bedtime boolean DEFAULT false,
    mood_context text,
    in_flow_state boolean DEFAULT false,
    focus_intensity double precision,
    body_state jsonb,
    body_state_context text,
    recent_shadow_summary text,
    shadow_tasks jsonb,
    shadow_decisions jsonb,
    shadow_questions jsonb,
    last_shadow_session_at timestamp with time zone,
    shadow_focus_areas jsonb,
    activity_state character varying(50),
    activity_confidence double precision,
    activity_reason text,
    activity_room character varying(100),
    interruptibility_score double precision,
    interruptibility_channel character varying(20),
    nudge_morning_eligible boolean DEFAULT false,
    nudge_bedtime_eligible boolean DEFAULT false,
    nudge_sleep_deficit double precision DEFAULT 0.0,
    recent_conversation_digest text
);


--
-- Name: surface; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.surface (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    conversation_id character varying(36),
    title character varying(255) NOT NULL,
    surface_type character varying(50) NOT NULL,
    spec jsonb NOT NULL,
    state jsonb NOT NULL,
    status character varying(20) NOT NULL,
    version integer NOT NULL,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: system_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_event (
    id integer NOT NULL,
    event_id character varying(64) NOT NULL,
    category character varying(32) DEFAULT 'log'::character varying NOT NULL,
    service character varying(128),
    level character varying(16),
    logger character varying(255),
    message text,
    traceback text,
    meta jsonb,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: system_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_event_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_event_id_seq OWNED BY public.system_event.id;


--
-- Name: tabata_preset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tabata_preset (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    name character varying NOT NULL,
    prepare_seconds integer,
    work_seconds integer NOT NULL,
    rest_seconds integer NOT NULL,
    rounds integer NOT NULL,
    sets integer,
    rest_between_sets_seconds integer,
    activity_type character varying,
    color character varying,
    is_built_in boolean,
    sort_order integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: tangent_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tangent_queue (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    parent_topic_id character varying NOT NULL,
    tangent_description text NOT NULL,
    source_context text,
    priority integer DEFAULT 3,
    status character varying(50) DEFAULT 'queued'::character varying,
    promoted_topic_id character varying,
    is_prerequisite boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: task_commit_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_commit_link (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    task_id character varying NOT NULL,
    commit_id character varying NOT NULL,
    auto_linked boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_failure; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_failure (
    id integer NOT NULL,
    task_name character varying(255) NOT NULL,
    error_class character varying(255) NOT NULL,
    error_message text,
    traceback text,
    event_id character varying(64),
    first_seen timestamp with time zone NOT NULL,
    last_seen timestamp with time zone NOT NULL,
    occurrences integer DEFAULT 1 NOT NULL,
    resolved boolean DEFAULT false NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: task_failure_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_failure_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_failure_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_failure_id_seq OWNED BY public.task_failure.id;


--
-- Name: task_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_item (
    id character varying DEFAULT (gen_random_uuid())::text NOT NULL,
    project_id character varying NOT NULL,
    user_id character varying NOT NULL,
    task_number integer NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    task_type character varying(20) DEFAULT 'task'::character varying NOT NULL,
    status character varying(20) DEFAULT 'backlog'::character varying NOT NULL,
    priority character varying(20),
    tags character varying[],
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: temerant_attribute_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_attribute_state (
    id character varying NOT NULL,
    character_id character varying NOT NULL,
    attribute character varying(32) NOT NULL,
    xp_total integer DEFAULT 0 NOT NULL,
    xp_term integer DEFAULT 0 NOT NULL,
    level integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_character; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_character (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_name text NOT NULL,
    backstory text,
    origin text,
    current_rank character varying(32) DEFAULT 'elir'::character varying NOT NULL,
    coin_balance double precision DEFAULT 0.0 NOT NULL,
    alar_strength integer DEFAULT 0 NOT NULL,
    naming_affinity integer DEFAULT 0 NOT NULL,
    specialization_track character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_temerant_character_rank CHECK (((current_rank)::text = ANY ((ARRAY['elir'::character varying, 'relar'::character varying, 'elthe'::character varying])::text[])))
);


--
-- Name: temerant_daily_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_daily_state (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    local_date date NOT NULL,
    categories_completed integer DEFAULT 0 NOT NULL,
    body_xp integer DEFAULT 0 NOT NULL,
    mind_xp integer DEFAULT 0 NOT NULL,
    craft_xp integer DEFAULT 0 NOT NULL,
    coin_xp integer DEFAULT 0 NOT NULL,
    name_xp integer DEFAULT 0 NOT NULL,
    oracle_roll_raw integer,
    oracle_roll_modified integer,
    oracle_event_id character varying,
    term_month date NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_ingestion_cursor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_ingestion_cursor (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    source_type character varying(64) NOT NULL,
    cursor_value character varying(255) NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_journal_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_journal_entry (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    local_date date NOT NULL,
    summary_structured jsonb DEFAULT '{}'::jsonb NOT NULL,
    summary_markdown text NOT NULL,
    source_event_count integer DEFAULT 0 NOT NULL,
    generated_by character varying(32) DEFAULT 'rules'::character varying NOT NULL,
    model character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_mapping_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_mapping_rule (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    source_kind character varying(64) NOT NULL,
    source_ref character varying(255),
    target_attribute character varying(32) NOT NULL,
    target_subdomain character varying(64),
    xp_base integer DEFAULT 1 NOT NULL,
    bonus_rules jsonb DEFAULT '{}'::jsonb NOT NULL,
    daily_cap integer,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_masterwork; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_masterwork (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    title text NOT NULL,
    description text,
    status character varying(32) DEFAULT 'planned'::character varying NOT NULL,
    evidence jsonb,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_oracle_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_oracle_event (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    thread_id character varying,
    local_date date NOT NULL,
    tier character varying(16) NOT NULL,
    category character varying(32) NOT NULL,
    title text NOT NULL,
    hook text NOT NULL,
    stakes text,
    options jsonb,
    resolution text,
    status character varying(16) DEFAULT 'open'::character varying NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: temerant_rpg_character; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_character (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_name text NOT NULL,
    origin text,
    backstory text,
    body integer DEFAULT 3 NOT NULL,
    mind integer DEFAULT 5 NOT NULL,
    craft integer DEFAULT 3 NOT NULL,
    voice integer DEFAULT 2 NOT NULL,
    luck integer DEFAULT 3 NOT NULL,
    coin_talents double precision DEFAULT 38.0 NOT NULL,
    rank character varying(32) DEFAULT 'none'::character varying NOT NULL,
    conditions jsonb DEFAULT '{}'::jsonb NOT NULL,
    skills jsonb DEFAULT '{}'::jsonb NOT NULL,
    inventory jsonb DEFAULT '[]'::jsonb NOT NULL,
    term_index integer DEFAULT 1 NOT NULL,
    current_scene_id character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_rpg_journal_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_journal_entry (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    local_date date NOT NULL,
    summary_markdown text NOT NULL,
    scene_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_rpg_relationship; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_relationship (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    npc_key character varying(64) NOT NULL,
    display_name character varying(128) NOT NULL,
    disposition character varying(24) DEFAULT 'neutral'::character varying NOT NULL,
    trust character varying(24) DEFAULT 'guarded'::character varying NOT NULL,
    respect character varying(24) DEFAULT 'neutral'::character varying NOT NULL,
    debt_balance integer DEFAULT 0 NOT NULL,
    notes text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_rpg_scene; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_scene (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    scene_number integer NOT NULL,
    local_date date NOT NULL,
    day_slot character varying(16) NOT NULL,
    location character varying(128) NOT NULL,
    title character varying(180) NOT NULL,
    opening_text text NOT NULL,
    status character varying(16) DEFAULT 'open'::character varying NOT NULL,
    summary text,
    consequences jsonb DEFAULT '[]'::jsonb NOT NULL,
    opened_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone
);


--
-- Name: temerant_rpg_scene_turn; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_scene_turn (
    id character varying NOT NULL,
    scene_id character varying NOT NULL,
    user_id character varying NOT NULL,
    turn_index integer NOT NULL,
    player_action text NOT NULL,
    gm_response text NOT NULL,
    resolution jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_rpg_term; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_term (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    term_index integer NOT NULL,
    month date NOT NULL,
    admissions_result character varying(24) DEFAULT 'mixed'::character varying NOT NULL,
    tuition_talents double precision DEFAULT 10.0 NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_rpg_world_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_rpg_world_state (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    local_date date NOT NULL,
    day_slot character varying(16) DEFAULT 'afternoon'::character varying NOT NULL,
    weather character varying(64) DEFAULT 'autumn chill'::character varying NOT NULL,
    location_hint character varying(128) DEFAULT 'Imre'::character varying NOT NULL,
    ambient_events jsonb DEFAULT '[]'::jsonb NOT NULL,
    pending_consequences jsonb DEFAULT '[]'::jsonb NOT NULL,
    last_advance_summary text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_story_thread; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_story_thread (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    title text NOT NULL,
    status character varying(32) DEFAULT 'open'::character varying NOT NULL,
    last_event_at timestamp with time zone,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_term; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_term (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    term_month date NOT NULL,
    completion_pct double precision DEFAULT 0.0 NOT NULL,
    admissions_result character varying(16) DEFAULT 'good'::character varying NOT NULL,
    tuition_talents integer DEFAULT 10 NOT NULL,
    xp_multiplier double precision DEFAULT 1.0 NOT NULL,
    coin_delta double precision DEFAULT 0.0 NOT NULL,
    review_markdown text,
    locked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: temerant_xp_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temerant_xp_ledger (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    character_id character varying NOT NULL,
    source_type character varying(64) NOT NULL,
    source_ref_id character varying(255),
    idempotency_key character varying(255) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    local_date date NOT NULL,
    attribute character varying(32) NOT NULL,
    subdomain character varying(64),
    xp_delta integer DEFAULT 0 NOT NULL,
    coin_delta double precision DEFAULT 0.0 NOT NULL,
    name_delta integer DEFAULT 0 NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: template_exercise; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template_exercise (
    id character varying NOT NULL,
    template_id character varying NOT NULL,
    exercise_name character varying(200) NOT NULL,
    order_index integer,
    target_sets integer,
    rep_range_low integer,
    rep_range_high integer,
    target_rpe numeric(3,1),
    rest_seconds integer,
    progression_rule character varying(50),
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    metric_type character varying(20) DEFAULT 'reps'::character varying NOT NULL,
    is_per_side boolean DEFAULT false NOT NULL,
    superset_group character varying(10),
    set_technique character varying(20)
);


--
-- Name: temporal_bin; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temporal_bin (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(36) NOT NULL,
    bin_date date NOT NULL,
    bin_hour integer,
    bin_type character varying(20) NOT NULL,
    git_metrics jsonb,
    health_metrics jsonb,
    food_metrics jsonb,
    home_metrics jsonb,
    mood_metrics jsonb,
    day_of_week integer,
    is_weekend boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    calendar_metrics jsonb
);


--
-- Name: timer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.timer (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    title character varying NOT NULL,
    duration_minutes integer NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone NOT NULL,
    is_active boolean,
    is_completed boolean,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: token_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_usage (
    id character varying(36) NOT NULL,
    user_id character varying(36),
    endpoint character varying(255) NOT NULL,
    model character varying(100) NOT NULL,
    operation_type character varying(50) NOT NULL,
    prompt_tokens integer NOT NULL,
    completion_tokens integer NOT NULL,
    total_tokens integer NOT NULL,
    session_id character varying(36),
    request_metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: token_usage_aggregate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_usage_aggregate (
    id character varying(36) NOT NULL,
    user_id character varying(36),
    total_prompt_tokens bigint NOT NULL,
    total_completion_tokens bigint NOT NULL,
    total_tokens bigint NOT NULL,
    total_requests bigint NOT NULL,
    last_reset_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: topic_connection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic_connection (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    source_topic_id character varying NOT NULL,
    target_topic_id character varying NOT NULL,
    connection_type character varying(50) NOT NULL,
    strength double precision,
    description text,
    auto_generated boolean,
    confirmed boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: topic_scratchpad; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic_scratchpad (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    topic_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    session_state jsonb DEFAULT '{}'::jsonb,
    last_interaction_at timestamp with time zone,
    curriculum jsonb
);


--
-- Name: topic_source; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic_source (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    topic_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    source_type character varying(50) NOT NULL,
    url text,
    title character varying(500),
    content_text text,
    quality_score double precision DEFAULT 0.5,
    origin_reputation double precision DEFAULT 0.5,
    fetch_status character varying(50) DEFAULT 'pending'::character varying,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    toc jsonb
);


--
-- Name: truth_maintenance_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.truth_maintenance_report (
    id bigint NOT NULL,
    user_id character varying(255) NOT NULL,
    ran_for_date date NOT NULL,
    counts jsonb DEFAULT '{}'::jsonb NOT NULL,
    flags jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: truth_maintenance_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.truth_maintenance_report_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: truth_maintenance_report_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.truth_maintenance_report_id_seq OWNED BY public.truth_maintenance_report.id;


--
-- Name: tunable_setting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tunable_setting (
    key character varying(120) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    value_type character varying(20) NOT NULL,
    value jsonb NOT NULL,
    default_value jsonb NOT NULL,
    min_value jsonb,
    max_value jsonb,
    unit character varying(50),
    editable boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_activity_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_activity_log (
    id character varying NOT NULL,
    user_id character varying,
    action_type character varying NOT NULL,
    action_description text,
    data_accessed jsonb DEFAULT '{}'::jsonb,
    ai_insights_generated jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: user_life_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_life_context (
    id integer NOT NULL,
    user_id character varying NOT NULL,
    active_goals json DEFAULT '[]'::json NOT NULL,
    current_habits json DEFAULT '[]'::json NOT NULL,
    current_projects json DEFAULT '[]'::json NOT NULL,
    health_status json DEFAULT '{}'::json NOT NULL,
    focus_mode character varying,
    stress_level integer,
    mood_profile json DEFAULT '{}'::json NOT NULL,
    energy_level integer,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_life_context_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_life_context_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_life_context_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_life_context_id_seq OWNED BY public.user_life_context.id;


--
-- Name: user_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_profile (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    mode_preferences text,
    autonomy_level character varying(20),
    quiet_hours_start character varying,
    quiet_hours_end character varying,
    idle_thresholds text,
    ntfy_enabled boolean,
    ntfy_topics text,
    sprite_notifications boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    profile_data jsonb DEFAULT '{}'::jsonb,
    communication_style character varying(20) DEFAULT 'friendly'::text,
    notification_channels jsonb DEFAULT '[]'::jsonb,
    gtky_completed_at timestamp with time zone,
    current_mode character varying DEFAULT 'companion'::character varying
);


--
-- Name: user_relationship; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_relationship (
    user_id character varying NOT NULL,
    relationship_score double precision DEFAULT 0.0,
    days_together integer DEFAULT 0,
    total_conversations integer DEFAULT 0,
    bugs_solved_together integer DEFAULT 0,
    notes_created_together integer DEFAULT 0,
    shared_milestones jsonb,
    inside_references jsonb,
    last_interaction timestamp with time zone
);


--
-- Name: TABLE user_relationship; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_relationship IS 'User-AI rapport and relationship tracking';


--
-- Name: user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_settings (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    vision_model character varying DEFAULT 'qwen3-vl:latest'::character varying,
    vision_endpoint character varying DEFAULT 'http://10.185.1.8:11434'::character varying,
    screenshot_enabled boolean DEFAULT true,
    screenshot_interval_seconds integer DEFAULT 30,
    screenshot_blur_sensitive boolean DEFAULT true,
    wake_word_enabled boolean DEFAULT true,
    activity_tracking_enabled boolean DEFAULT true,
    cross_device_commands_enabled boolean DEFAULT true,
    preferences jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: voice_interaction_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voice_interaction_log (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone,
    turns integer DEFAULT 0 NOT NULL,
    duration_seconds double precision,
    summary text,
    source character varying DEFAULT 'jetson_voice'::character varying NOT NULL
);


--
-- Name: weight_trend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.weight_trend (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    date date NOT NULL,
    raw_weight numeric(5,2) NOT NULL,
    trend_weight numeric(5,2),
    weekly_delta numeric(5,2),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workout; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    plan_id character varying,
    title character varying NOT NULL,
    phase character varying,
    week integer,
    day_of_week integer,
    duration_min integer,
    prescription json,
    status character varying,
    calendar_event_id character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: workout_adjustment_proposal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_adjustment_proposal (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    session_id character varying(36),
    kind character varying(40) NOT NULL,
    scope jsonb,
    current_value jsonb,
    proposed_value jsonb,
    reason text,
    evidence jsonb,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    resolved_at timestamp with time zone,
    resolved_by_device character varying(20),
    approval_command_id character varying(64)
);


--
-- Name: workout_approved_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_approved_policy (
    user_id character varying(36) NOT NULL,
    policy jsonb NOT NULL,
    approved_at timestamp with time zone DEFAULT now(),
    approved_by_device character varying(20),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: workout_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_log (
    id character varying NOT NULL,
    workout_id character varying NOT NULL,
    user_id character varying NOT NULL,
    exercise_id character varying,
    set_index integer NOT NULL,
    weight integer,
    reps integer,
    rpe integer,
    notes text,
    flags json,
    created_at timestamp with time zone DEFAULT now(),
    template_id character varying,
    session_date date,
    day_of_week character varying,
    session_id character varying,
    session_time timestamp with time zone,
    template_exercise_id character varying,
    set_number integer,
    is_pr boolean,
    skipped boolean,
    active_session_id character varying(36),
    exercise_library_id character varying,
    command_id character varying(64),
    set_kind character varying(12) DEFAULT 'working'::character varying NOT NULL,
    parent_set_id character varying(36),
    set_group_id character varying(36),
    group_sequence integer DEFAULT 0 NOT NULL,
    counts_toward_target boolean DEFAULT true NOT NULL,
    voided_at timestamp with time zone,
    void_reason character varying(120),
    revised_from_set_id character varying(36),
    CONSTRAINT ck_workout_log_set_kind CHECK (((set_kind)::text = ANY ((ARRAY['working'::character varying, 'warmup'::character varying, 'drop'::character varying])::text[])))
);


--
-- Name: workout_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_session (
    id character varying NOT NULL,
    user_id character varying NOT NULL,
    template_id character varying,
    session_date date NOT NULL,
    status character varying DEFAULT 'planned'::character varying NOT NULL,
    calendar_event_id character varying,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    active_session_id character varying(36),
    CONSTRAINT workout_session_status_check CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'skipped'::character varying])::text[])))
);


--
-- Name: workout_session_command; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_session_command (
    command_id character varying(64) NOT NULL,
    session_id character varying(36),
    user_id character varying(36) NOT NULL,
    origin_device character varying(20),
    kind character varying(40) NOT NULL,
    expected_version bigint,
    payload jsonb,
    result jsonb,
    status character varying(20) DEFAULT 'applied'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    applied_at timestamp with time zone
);


--
-- Name: workout_session_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workout_session_event (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    after_version bigint,
    kind character varying(40) NOT NULL,
    text text,
    speak boolean DEFAULT false NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    proposal_id character varying(36),
    payload jsonb,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone
);


--
-- Name: workspace_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_job (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    job_type character varying(50) NOT NULL,
    params jsonb NOT NULL,
    status character varying(20) NOT NULL,
    surface_id character varying(36),
    result jsonb NOT NULL,
    error character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone
);


--
-- Name: workspace_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_states (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    state_data jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: world_attention_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_attention_item (
    id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    source_event_id character varying(36) NOT NULL,
    source_fact_id character varying(36),
    source_thread_id character varying(36),
    domain character varying(64) NOT NULL,
    description text NOT NULL,
    salience double precision DEFAULT '0'::double precision NOT NULL,
    novelty double precision DEFAULT '0'::double precision NOT NULL,
    urgency double precision DEFAULT '0'::double precision NOT NULL,
    uncertainty double precision DEFAULT '0'::double precision NOT NULL,
    actionability double precision DEFAULT '0'::double precision NOT NULL,
    aggregate_score double precision DEFAULT '0'::double precision NOT NULL,
    coalesce_key character varying(768) NOT NULL,
    occurrence_count integer DEFAULT 1 NOT NULL,
    status character varying(24) DEFAULT 'queued'::character varying NOT NULL,
    valid_until timestamp with time zone,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: world_brief; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_brief (
    user_id character varying(255) NOT NULL,
    sections jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_brief_patch_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_brief_patch_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(255) NOT NULL,
    op character varying(20) NOT NULL,
    section character varying(50) NOT NULL,
    item_key character varying(200),
    content jsonb,
    source character varying(100) NOT NULL,
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_entity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_entity (
    id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    kind character varying(64) NOT NULL,
    canonical_key character varying(512) NOT NULL,
    display_name character varying(512) NOT NULL,
    aliases jsonb DEFAULT '[]'::jsonb NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(24) DEFAULT 'active'::character varying NOT NULL,
    merged_into_id character varying(36),
    first_event_id character varying(36),
    last_event_id character varying(36),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_event (
    sequence bigint NOT NULL,
    event_id character varying(36) NOT NULL,
    schema_version integer DEFAULT 2 NOT NULL,
    user_id character varying NOT NULL,
    kind character varying(128) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    committed_at timestamp with time zone DEFAULT now() NOT NULL,
    source character varying(128) NOT NULL,
    source_ref character varying(512),
    aggregate_type character varying(128),
    aggregate_id character varying(255),
    aggregate_version bigint,
    actor_type character varying(32) DEFAULT 'system'::character varying NOT NULL,
    actor_id character varying(255),
    correlation_id character varying(128),
    causation_id character varying(36),
    dedupe_key character varying(512) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    provenance jsonb DEFAULT '{}'::jsonb NOT NULL,
    confidence double precision DEFAULT '1'::double precision NOT NULL,
    confidence_basis character varying(16) DEFAULT 'observed'::character varying NOT NULL,
    sensitivity character varying(32) DEFAULT 'normal'::character varying NOT NULL,
    retention_class character varying(32) DEFAULT 'standard'::character varying NOT NULL,
    is_backfill boolean DEFAULT false NOT NULL
);


--
-- Name: world_event_disposition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_event_disposition (
    id bigint NOT NULL,
    event_id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    reducer_version integer DEFAULT 1 NOT NULL,
    outcomes jsonb DEFAULT '[]'::jsonb NOT NULL,
    reason text NOT NULL,
    state_delta jsonb DEFAULT '{}'::jsonb NOT NULL,
    output_ids jsonb DEFAULT '{}'::jsonb NOT NULL,
    policy_version character varying(64) DEFAULT 'world-state-v1'::character varying NOT NULL,
    model_version character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_event_disposition_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.world_event_disposition_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: world_event_disposition_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.world_event_disposition_id_seq OWNED BY public.world_event_disposition.id;


--
-- Name: world_event_processing; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_event_processing (
    id bigint NOT NULL,
    event_id character varying(36) NOT NULL,
    status character varying(24) DEFAULT 'pending'::character varying NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone,
    leased_until timestamp with time zone,
    worker_id character varying(255),
    last_error text,
    reducer_version integer DEFAULT 1 NOT NULL,
    interpreter_status character varying(24) DEFAULT 'not_needed'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    interpreter_attempt_count integer DEFAULT 0 NOT NULL
);


--
-- Name: world_event_processing_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.world_event_processing_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: world_event_processing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.world_event_processing_id_seq OWNED BY public.world_event_processing.id;


--
-- Name: world_event_sequence_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.world_event_sequence_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: world_event_sequence_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.world_event_sequence_seq OWNED BY public.world_event.sequence;


--
-- Name: world_fact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_fact (
    id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    fact_key character varying(768) NOT NULL,
    subject_entity_id character varying(36),
    predicate character varying(255) NOT NULL,
    object_entity_id character varying(36),
    value jsonb,
    valid_from timestamp with time zone,
    valid_to timestamp with time zone,
    observed_at timestamp with time zone NOT NULL,
    status character varying(24) DEFAULT 'active'::character varying NOT NULL,
    confidence double precision DEFAULT '1'::double precision NOT NULL,
    confidence_basis character varying(16) DEFAULT 'observed'::character varying NOT NULL,
    source_event_id character varying(36) NOT NULL,
    source_ref character varying(512),
    extractor_version character varying(128),
    supersedes_fact_id character varying(36),
    retracted_by_event_id character varying(36),
    last_event_sequence bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_snapshot (
    user_id character varying NOT NULL,
    schema_version integer DEFAULT 2 NOT NULL,
    revision bigint DEFAULT '0'::bigint NOT NULL,
    last_event_sequence bigint DEFAULT '0'::bigint NOT NULL,
    snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    coverage jsonb DEFAULT '{}'::jsonb NOT NULL,
    as_of timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: world_thread; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.world_thread (
    id character varying(36) NOT NULL,
    user_id character varying NOT NULL,
    thread_key character varying(768) NOT NULL,
    kind character varying(32) NOT NULL,
    status character varying(24) DEFAULT 'open'::character varying NOT NULL,
    title text NOT NULL,
    next_step text,
    owner_entity_id character varying(36),
    counterparty_entity_id character varying(36),
    due_at timestamp with time zone,
    next_review_at timestamp with time zone,
    priority double precision DEFAULT '0.5'::double precision NOT NULL,
    confidence double precision DEFAULT '1'::double precision NOT NULL,
    source_event_id character varying(36) NOT NULL,
    source_fact_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    correlation_id character varying(128),
    last_event_sequence bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    due_provenance character varying(200)
);


--
-- Name: action_ledger id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_ledger ALTER COLUMN id SET DEFAULT nextval('public.action_ledger_id_seq'::regclass);


--
-- Name: action_why_trace id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_why_trace ALTER COLUMN id SET DEFAULT nextval('public.action_why_trace_id_seq'::regclass);


--
-- Name: agent_run_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_log ALTER COLUMN id SET DEFAULT nextval('public.agent_run_log_id_seq'::regclass);


--
-- Name: automation_execution_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_execution_log ALTER COLUMN id SET DEFAULT nextval('public.automation_execution_log_id_seq'::regclass);


--
-- Name: automation_state_store id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_state_store ALTER COLUMN id SET DEFAULT nextval('public.automation_state_store_id_seq'::regclass);


--
-- Name: chat_turn_trace id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_turn_trace ALTER COLUMN id SET DEFAULT nextval('public.chat_turn_trace_id_seq'::regclass);


--
-- Name: consolidation_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_config ALTER COLUMN id SET DEFAULT nextval('public.consolidation_config_id_seq'::regclass);


--
-- Name: consolidation_discards id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_discards ALTER COLUMN id SET DEFAULT nextval('public.consolidation_discards_id_seq'::regclass);


--
-- Name: context_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots ALTER COLUMN id SET DEFAULT nextval('public.context_snapshots_id_seq'::regclass);


--
-- Name: correction id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction ALTER COLUMN id SET DEFAULT nextval('public.correction_id_seq'::regclass);


--
-- Name: day_type_override id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_type_override ALTER COLUMN id SET DEFAULT nextval('public.day_type_override_id_seq'::regclass);


--
-- Name: directive id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directive ALTER COLUMN id SET DEFAULT nextval('public.directive_id_seq'::regclass);


--
-- Name: event_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_log ALTER COLUMN id SET DEFAULT nextval('public.event_log_id_seq'::regclass);


--
-- Name: event_outbox id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_outbox ALTER COLUMN id SET DEFAULT nextval('public.event_outbox_id_seq'::regclass);


--
-- Name: goal id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goal ALTER COLUMN id SET DEFAULT nextval('public.goal_id_seq'::regclass);


--
-- Name: goal_progress id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goal_progress ALTER COLUMN id SET DEFAULT nextval('public.goal_progress_id_seq'::regclass);


--
-- Name: heartbeat_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.heartbeat_items ALTER COLUMN id SET DEFAULT nextval('public.heartbeat_items_id_seq'::regclass);


--
-- Name: heartbeat_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.heartbeat_logs ALTER COLUMN id SET DEFAULT nextval('public.heartbeat_logs_id_seq'::regclass);


--
-- Name: held_notification id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_notification ALTER COLUMN id SET DEFAULT nextval('public.held_notification_id_seq'::regclass);


--
-- Name: home_state_summary id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.home_state_summary ALTER COLUMN id SET DEFAULT nextval('public.home_state_summary_id_seq'::regclass);


--
-- Name: host_alert id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_alert ALTER COLUMN id SET DEFAULT nextval('public.host_alert_id_seq'::regclass);


--
-- Name: host_diag_command id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_diag_command ALTER COLUMN id SET DEFAULT nextval('public.host_diag_command_id_seq'::regclass);


--
-- Name: host_metric id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_metric ALTER COLUMN id SET DEFAULT nextval('public.host_metric_id_seq'::regclass);


--
-- Name: intelligence_report id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_report ALTER COLUMN id SET DEFAULT nextval('public.intelligence_report_id_seq'::regclass);


--
-- Name: karma_dimensions dimension_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_dimensions ALTER COLUMN dimension_id SET DEFAULT nextval('public.karma_dimensions_dimension_id_seq'::regclass);


--
-- Name: karma_scores score_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_scores ALTER COLUMN score_id SET DEFAULT nextval('public.karma_scores_score_id_seq'::regclass);


--
-- Name: life_fact id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.life_fact ALTER COLUMN id SET DEFAULT nextval('public.life_fact_id_seq'::regclass);


--
-- Name: list_item id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_item ALTER COLUMN id SET DEFAULT nextval('public.list_item_id_seq'::regclass);


--
-- Name: notification_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_log ALTER COLUMN id SET DEFAULT nextval('public.notification_log_id_seq'::regclass);


--
-- Name: notification_preference id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_preference ALTER COLUMN id SET DEFAULT nextval('public.notification_preference_id_seq'::regclass);


--
-- Name: notification_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_queue ALTER COLUMN id SET DEFAULT nextval('public.notification_queue_id_seq'::regclass);


--
-- Name: outbox_usage_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_usage_log ALTER COLUMN id SET DEFAULT nextval('public.outbox_usage_log_id_seq'::regclass);


--
-- Name: prompt_proposals proposal_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_proposals ALTER COLUMN proposal_id SET DEFAULT nextval('public.prompt_proposals_proposal_id_seq'::regclass);


--
-- Name: prompt_versions version_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_versions ALTER COLUMN version_id SET DEFAULT nextval('public.prompt_versions_version_id_seq'::regclass);


--
-- Name: raw_buffer_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_buffer_stats ALTER COLUMN id SET DEFAULT nextval('public.raw_buffer_stats_id_seq'::regclass);


--
-- Name: reflection_hypotheses hypothesis_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_hypotheses ALTER COLUMN hypothesis_id SET DEFAULT nextval('public.reflection_hypotheses_hypothesis_id_seq'::regclass);


--
-- Name: reflection_observations observation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_observations ALTER COLUMN observation_id SET DEFAULT nextval('public.reflection_observations_observation_id_seq'::regclass);


--
-- Name: registered_endpoint id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registered_endpoint ALTER COLUMN id SET DEFAULT nextval('public.registered_endpoint_id_seq'::regclass);


--
-- Name: research_brief id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_brief ALTER COLUMN id SET DEFAULT nextval('public.research_brief_id_seq'::regclass);


--
-- Name: sara_soul id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_soul ALTER COLUMN id SET DEFAULT nextval('public.sara_soul_id_seq'::regclass);


--
-- Name: scheduled_home_action id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_home_action ALTER COLUMN id SET DEFAULT nextval('public.scheduled_home_action_id_seq'::regclass);


--
-- Name: scratchpad_entry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scratchpad_entry ALTER COLUMN id SET DEFAULT nextval('public.scratchpad_entry_id_seq'::regclass);


--
-- Name: singular_context_turn_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.singular_context_turn_log ALTER COLUMN id SET DEFAULT nextval('public.singular_context_turn_log_id_seq'::regclass);


--
-- Name: soul_change_proposals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.soul_change_proposals ALTER COLUMN id SET DEFAULT nextval('public.soul_change_proposals_id_seq'::regclass);


--
-- Name: standing_order id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.standing_order ALTER COLUMN id SET DEFAULT nextval('public.standing_order_id_seq'::regclass);


--
-- Name: stimulus_habituation id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stimulus_habituation ALTER COLUMN id SET DEFAULT nextval('public.stimulus_habituation_id_seq'::regclass);


--
-- Name: system_event id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_event ALTER COLUMN id SET DEFAULT nextval('public.system_event_id_seq'::regclass);


--
-- Name: task_failure id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_failure ALTER COLUMN id SET DEFAULT nextval('public.task_failure_id_seq'::regclass);


--
-- Name: truth_maintenance_report id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.truth_maintenance_report ALTER COLUMN id SET DEFAULT nextval('public.truth_maintenance_report_id_seq'::regclass);


--
-- Name: user_life_context id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_life_context ALTER COLUMN id SET DEFAULT nextval('public.user_life_context_id_seq'::regclass);


--
-- Name: world_event sequence; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event ALTER COLUMN sequence SET DEFAULT nextval('public.world_event_sequence_seq'::regclass);


--
-- Name: world_event_disposition id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_disposition ALTER COLUMN id SET DEFAULT nextval('public.world_event_disposition_id_seq'::regclass);


--
-- Name: world_event_processing id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_processing ALTER COLUMN id SET DEFAULT nextval('public.world_event_processing_id_seq'::regclass);


--
-- Name: achievement achievement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.achievement
    ADD CONSTRAINT achievement_pkey PRIMARY KEY (id);


--
-- Name: action_ledger action_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_ledger
    ADD CONSTRAINT action_ledger_pkey PRIMARY KEY (id);


--
-- Name: action_log action_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_log
    ADD CONSTRAINT action_log_pkey PRIMARY KEY (action_id);


--
-- Name: action_receipt action_receipt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_receipt
    ADD CONSTRAINT action_receipt_pkey PRIMARY KEY (action_id);


--
-- Name: action_why_trace action_why_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_why_trace
    ADD CONSTRAINT action_why_trace_pkey PRIMARY KEY (id);


--
-- Name: active_workout_session active_workout_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_workout_session
    ADD CONSTRAINT active_workout_session_pkey PRIMARY KEY (id);


--
-- Name: activity_session activity_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_session
    ADD CONSTRAINT activity_session_pkey PRIMARY KEY (id);


--
-- Name: agent_run_log agent_run_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_log
    ADD CONSTRAINT agent_run_log_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: anchor_point anchor_point_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anchor_point
    ADD CONSTRAINT anchor_point_pkey PRIMARY KEY (id);


--
-- Name: app_settings app_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: app_user_role app_user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_role
    ADD CONSTRAINT app_user_role_pkey PRIMARY KEY (user_id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: attention_item attention_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attention_item
    ADD CONSTRAINT attention_item_pkey PRIMARY KEY (attention_item_id);


--
-- Name: attention_policy attention_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attention_policy
    ADD CONSTRAINT attention_policy_pkey PRIMARY KEY (id);


--
-- Name: attention_policy_snapshot attention_policy_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attention_policy_snapshot
    ADD CONSTRAINT attention_policy_snapshot_pkey PRIMARY KEY (id);


--
-- Name: attention_policy attention_policy_user_id_domain_context_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attention_policy
    ADD CONSTRAINT attention_policy_user_id_domain_context_key UNIQUE (user_id, domain, context);


--
-- Name: automation_execution_log automation_execution_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_execution_log
    ADD CONSTRAINT automation_execution_log_pkey PRIMARY KEY (id);


--
-- Name: automation_state_store automation_state_store_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_state_store
    ADD CONSTRAINT automation_state_store_pkey PRIMARY KEY (id);


--
-- Name: automation_task automation_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_task
    ADD CONSTRAINT automation_task_pkey PRIMARY KEY (id);


--
-- Name: autonomous_insight autonomous_insight_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomous_insight
    ADD CONSTRAINT autonomous_insight_pkey PRIMARY KEY (id);


--
-- Name: autonomy_action_trace autonomy_action_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_action_trace
    ADD CONSTRAINT autonomy_action_trace_pkey PRIMARY KEY (id);


--
-- Name: autonomy_mission autonomy_mission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_mission
    ADD CONSTRAINT autonomy_mission_pkey PRIMARY KEY (id);


--
-- Name: autonomy_mission_step autonomy_mission_step_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_mission_step
    ADD CONSTRAINT autonomy_mission_step_pkey PRIMARY KEY (id);


--
-- Name: autonomy_trust autonomy_trust_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_trust
    ADD CONSTRAINT autonomy_trust_pkey PRIMARY KEY (action_class);


--
-- Name: background_sweep background_sweep_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.background_sweep
    ADD CONSTRAINT background_sweep_pkey PRIMARY KEY (id);


--
-- Name: background_task background_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.background_task
    ADD CONSTRAINT background_task_pkey PRIMARY KEY (id);


--
-- Name: behavioral_pattern behavioral_pattern_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavioral_pattern
    ADD CONSTRAINT behavioral_pattern_pkey PRIMARY KEY (id);


--
-- Name: body_capability body_capability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_capability
    ADD CONSTRAINT body_capability_pkey PRIMARY KEY (name);


--
-- Name: body_state_calibration body_state_calibration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_state_calibration
    ADD CONSTRAINT body_state_calibration_pkey PRIMARY KEY (id);


--
-- Name: body_state_coefficients body_state_coefficients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_state_coefficients
    ADD CONSTRAINT body_state_coefficients_pkey PRIMARY KEY (id);


--
-- Name: body_state_coefficients body_state_coefficients_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_state_coefficients
    ADD CONSTRAINT body_state_coefficients_user_id_key UNIQUE (user_id);


--
-- Name: briefing_settings briefing_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.briefing_settings
    ADD CONSTRAINT briefing_settings_pkey PRIMARY KEY (id);


--
-- Name: calendar_event calendar_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event
    ADD CONSTRAINT calendar_event_pkey PRIMARY KEY (id);


--
-- Name: candidate_skill candidate_skill_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_skill
    ADD CONSTRAINT candidate_skill_pkey PRIMARY KEY (id);


--
-- Name: cardio_log cardio_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cardio_log
    ADD CONSTRAINT cardio_log_pkey PRIMARY KEY (id);


--
-- Name: cardio_settings cardio_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cardio_settings
    ADD CONSTRAINT cardio_settings_pkey PRIMARY KEY (user_id);


--
-- Name: chat_turn_trace chat_turn_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_turn_trace
    ADD CONSTRAINT chat_turn_trace_pkey PRIMARY KEY (id);


--
-- Name: chess_coaching_progress chess_coaching_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_coaching_progress
    ADD CONSTRAINT chess_coaching_progress_pkey PRIMARY KEY (id);


--
-- Name: chess_coaching_progress chess_coaching_progress_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_coaching_progress
    ADD CONSTRAINT chess_coaching_progress_user_id_key UNIQUE (user_id);


--
-- Name: chess_game chess_game_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_game
    ADD CONSTRAINT chess_game_pkey PRIMARY KEY (id);


--
-- Name: chess_stats chess_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_stats
    ADD CONSTRAINT chess_stats_pkey PRIMARY KEY (id);


--
-- Name: chess_stats chess_stats_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_stats
    ADD CONSTRAINT chess_stats_user_id_key UNIQUE (user_id);


--
-- Name: code_session code_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.code_session
    ADD CONSTRAINT code_session_pkey PRIMARY KEY (id);


--
-- Name: composed_utterance composed_utterance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.composed_utterance
    ADD CONSTRAINT composed_utterance_pkey PRIMARY KEY (id);


--
-- Name: consolidation_config consolidation_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_config
    ADD CONSTRAINT consolidation_config_pkey PRIMARY KEY (id);


--
-- Name: consolidation_config consolidation_config_user_id_config_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_config
    ADD CONSTRAINT consolidation_config_user_id_config_key_key UNIQUE (user_id, config_key);


--
-- Name: consolidation_discards consolidation_discards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_discards
    ADD CONSTRAINT consolidation_discards_pkey PRIMARY KEY (id);


--
-- Name: consolidation_runs consolidation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_runs
    ADD CONSTRAINT consolidation_runs_pkey PRIMARY KEY (id);


--
-- Name: context_modes context_modes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_modes
    ADD CONSTRAINT context_modes_pkey PRIMARY KEY (id);


--
-- Name: context_modes context_modes_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_modes
    ADD CONSTRAINT context_modes_user_id_key UNIQUE (user_id);


--
-- Name: context_snapshots context_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT context_snapshots_pkey PRIMARY KEY (id);


--
-- Name: context_window context_window_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_window
    ADD CONSTRAINT context_window_pkey PRIMARY KEY (id);


--
-- Name: conversation conversation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_pkey PRIMARY KEY (id);


--
-- Name: conversation_thread conversation_thread_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_thread
    ADD CONSTRAINT conversation_thread_pkey PRIMARY KEY (id);


--
-- Name: conversation_turn conversation_turn_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turn
    ADD CONSTRAINT conversation_turn_pkey PRIMARY KEY (id);


--
-- Name: correction correction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction
    ADD CONSTRAINT correction_pkey PRIMARY KEY (id);


--
-- Name: correlation_pattern correlation_pattern_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correlation_pattern
    ADD CONSTRAINT correlation_pattern_pkey PRIMARY KEY (id);


--
-- Name: daily_briefings daily_briefings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_briefings
    ADD CONSTRAINT daily_briefings_pkey PRIMARY KEY (id);


--
-- Name: daily_briefs daily_briefs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_briefs
    ADD CONSTRAINT daily_briefs_pkey PRIMARY KEY (id);


--
-- Name: daily_recovery_log daily_recovery_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_recovery_log
    ADD CONSTRAINT daily_recovery_log_pkey PRIMARY KEY (id);


--
-- Name: daily_recovery_log daily_recovery_log_user_id_log_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_recovery_log
    ADD CONSTRAINT daily_recovery_log_user_id_log_date_key UNIQUE (user_id, log_date);


--
-- Name: daily_reflections daily_reflections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_reflections
    ADD CONSTRAINT daily_reflections_pkey PRIMARY KEY (id);


--
-- Name: daily_rhythm daily_rhythm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_rhythm
    ADD CONSTRAINT daily_rhythm_pkey PRIMARY KEY (id);


--
-- Name: daily_task daily_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_task
    ADD CONSTRAINT daily_task_pkey PRIMARY KEY (id);


--
-- Name: day_replay_cache day_replay_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_replay_cache
    ADD CONSTRAINT day_replay_cache_pkey PRIMARY KEY (id);


--
-- Name: day_replay_cache day_replay_cache_user_id_replay_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_replay_cache
    ADD CONSTRAINT day_replay_cache_user_id_replay_date_key UNIQUE (user_id, replay_date);


--
-- Name: day_type_override day_type_override_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_type_override
    ADD CONSTRAINT day_type_override_pkey PRIMARY KEY (id);


--
-- Name: desktop_focus_span desktop_focus_span_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desktop_focus_span
    ADD CONSTRAINT desktop_focus_span_pkey PRIMARY KEY (id);


--
-- Name: dev_project dev_project_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dev_project
    ADD CONSTRAINT dev_project_pkey PRIMARY KEY (id);


--
-- Name: device_registration device_registration_device_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_registration
    ADD CONSTRAINT device_registration_device_token_key UNIQUE (device_token);


--
-- Name: device_registration device_registration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_registration
    ADD CONSTRAINT device_registration_pkey PRIMARY KEY (id);


--
-- Name: directive directive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directive
    ADD CONSTRAINT directive_pkey PRIMARY KEY (id);


--
-- Name: doc_chunk doc_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_chunk
    ADD CONSTRAINT doc_chunk_pkey PRIMARY KEY (id);


--
-- Name: document_chunk document_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_chunk
    ADD CONSTRAINT document_chunk_pkey PRIMARY KEY (id);


--
-- Name: document document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (id);


--
-- Name: dream_insight dream_insight_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dream_insight
    ADD CONSTRAINT dream_insight_pkey PRIMARY KEY (id);


--
-- Name: email_attachment email_attachment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_attachment
    ADD CONSTRAINT email_attachment_pkey PRIMARY KEY (id);


--
-- Name: email email_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email
    ADD CONSTRAINT email_pkey PRIMARY KEY (id);


--
-- Name: email_sync_state email_sync_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_sync_state
    ADD CONSTRAINT email_sync_state_pkey PRIMARY KEY (id);


--
-- Name: episode episode_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode
    ADD CONSTRAINT episode_pkey PRIMARY KEY (id);


--
-- Name: episode_rating episode_rating_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode_rating
    ADD CONSTRAINT episode_rating_pkey PRIMARY KEY (episode_id);


--
-- Name: episode_thread_mapping episode_thread_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode_thread_mapping
    ADD CONSTRAINT episode_thread_mapping_pkey PRIMARY KEY (episode_id, thread_id);


--
-- Name: event_log event_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_log
    ADD CONSTRAINT event_log_pkey PRIMARY KEY (id);


--
-- Name: event_outbox event_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_outbox
    ADD CONSTRAINT event_outbox_pkey PRIMARY KEY (id);


--
-- Name: event event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_pkey PRIMARY KEY (id);


--
-- Name: exercise_library exercise_library_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_library
    ADD CONSTRAINT exercise_library_pkey PRIMARY KEY (id);


--
-- Name: exercise_pr exercise_pr_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_pr
    ADD CONSTRAINT exercise_pr_pkey PRIMARY KEY (id);


--
-- Name: external_workout external_workout_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_workout
    ADD CONSTRAINT external_workout_pkey PRIMARY KEY (id);


--
-- Name: fatsecret_food_cache fatsecret_food_cache_fatsecret_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fatsecret_food_cache
    ADD CONSTRAINT fatsecret_food_cache_fatsecret_id_key UNIQUE (fatsecret_id);


--
-- Name: fatsecret_food_cache fatsecret_food_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fatsecret_food_cache
    ADD CONSTRAINT fatsecret_food_cache_pkey PRIMARY KEY (id);


--
-- Name: fitness_daily_log fitness_daily_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_daily_log
    ADD CONSTRAINT fitness_daily_log_pkey PRIMARY KEY (id);


--
-- Name: fitness_daily_log fitness_daily_log_user_id_log_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_daily_log
    ADD CONSTRAINT fitness_daily_log_user_id_log_date_key UNIQUE (user_id, log_date);


--
-- Name: fitness_goals fitness_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_goals
    ADD CONSTRAINT fitness_goals_pkey PRIMARY KEY (id);


--
-- Name: fitness_goals fitness_goals_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_goals
    ADD CONSTRAINT fitness_goals_user_id_key UNIQUE (user_id);


--
-- Name: fitness_idempotency fitness_idempotency_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_idempotency
    ADD CONSTRAINT fitness_idempotency_pkey PRIMARY KEY (id);


--
-- Name: fitness_note fitness_note_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_note
    ADD CONSTRAINT fitness_note_pkey PRIMARY KEY (id);


--
-- Name: fitness_phase fitness_phase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_phase
    ADD CONSTRAINT fitness_phase_pkey PRIMARY KEY (id);


--
-- Name: fitness_plan fitness_plan_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_plan
    ADD CONSTRAINT fitness_plan_pkey PRIMARY KEY (id);


--
-- Name: fitness_program fitness_program_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_program
    ADD CONSTRAINT fitness_program_pkey PRIMARY KEY (id);


--
-- Name: fitness_settings fitness_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_settings
    ADD CONSTRAINT fitness_settings_pkey PRIMARY KEY (id);


--
-- Name: fitness_settings fitness_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_settings
    ADD CONSTRAINT fitness_settings_user_id_key UNIQUE (user_id);


--
-- Name: fitness_template fitness_template_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_template
    ADD CONSTRAINT fitness_template_pkey PRIMARY KEY (id);


--
-- Name: folder folder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.folder
    ADD CONSTRAINT folder_pkey PRIMARY KEY (id);


--
-- Name: followup_thread followup_thread_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_thread
    ADD CONSTRAINT followup_thread_pkey PRIMARY KEY (id);


--
-- Name: food_database food_database_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_database
    ADD CONSTRAINT food_database_pkey PRIMARY KEY (id);


--
-- Name: food_log_item food_log_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_log_item
    ADD CONSTRAINT food_log_item_pkey PRIMARY KEY (id);


--
-- Name: food_log food_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_log
    ADD CONSTRAINT food_log_pkey PRIMARY KEY (id);


--
-- Name: git_branch git_branch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_branch
    ADD CONSTRAINT git_branch_pkey PRIMARY KEY (id);


--
-- Name: git_commit git_commit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_commit
    ADD CONSTRAINT git_commit_pkey PRIMARY KEY (id);


--
-- Name: goal goal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goal
    ADD CONSTRAINT goal_pkey PRIMARY KEY (id);


--
-- Name: goal_progress goal_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goal_progress
    ADD CONSTRAINT goal_progress_pkey PRIMARY KEY (id);


--
-- Name: gtky_sessions gtky_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gtky_sessions
    ADD CONSTRAINT gtky_sessions_pkey PRIMARY KEY (id);


--
-- Name: health_alert health_alert_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_alert
    ADD CONSTRAINT health_alert_pkey PRIMARY KEY (id);


--
-- Name: health_baseline health_baseline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_baseline
    ADD CONSTRAINT health_baseline_pkey PRIMARY KEY (id);


--
-- Name: health_insight health_insight_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_insight
    ADD CONSTRAINT health_insight_pkey PRIMARY KEY (id);


--
-- Name: health_metric health_metric_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_metric
    ADD CONSTRAINT health_metric_pkey PRIMARY KEY (id);


--
-- Name: health_weekly_report health_weekly_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_weekly_report
    ADD CONSTRAINT health_weekly_report_pkey PRIMARY KEY (id);


--
-- Name: heartbeat_items heartbeat_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.heartbeat_items
    ADD CONSTRAINT heartbeat_items_pkey PRIMARY KEY (id);


--
-- Name: heartbeat_logs heartbeat_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.heartbeat_logs
    ADD CONSTRAINT heartbeat_logs_pkey PRIMARY KEY (id);


--
-- Name: held_notification held_notification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_notification
    ADD CONSTRAINT held_notification_pkey PRIMARY KEY (id);


--
-- Name: home_activity_log home_activity_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.home_activity_log
    ADD CONSTRAINT home_activity_log_pkey PRIMARY KEY (id);


--
-- Name: home_state_summary home_state_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.home_state_summary
    ADD CONSTRAINT home_state_summary_pkey PRIMARY KEY (id);


--
-- Name: host_alert host_alert_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_alert
    ADD CONSTRAINT host_alert_pkey PRIMARY KEY (id);


--
-- Name: host_diag_command host_diag_command_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_diag_command
    ADD CONSTRAINT host_diag_command_pkey PRIMARY KEY (id);


--
-- Name: host_metric host_metric_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_metric
    ADD CONSTRAINT host_metric_pkey PRIMARY KEY (id);


--
-- Name: hypothesis hypothesis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hypothesis
    ADD CONSTRAINT hypothesis_pkey PRIMARY KEY (id);


--
-- Name: insight_mention_log insight_mention_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_mention_log
    ADD CONSTRAINT insight_mention_log_pkey PRIMARY KEY (id);


--
-- Name: insight_nudge insight_nudge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_nudge
    ADD CONSTRAINT insight_nudge_pkey PRIMARY KEY (id);


--
-- Name: intelligence_item intelligence_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_item
    ADD CONSTRAINT intelligence_item_pkey PRIMARY KEY (id);


--
-- Name: intelligence_report intelligence_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_report
    ADD CONSTRAINT intelligence_report_pkey PRIMARY KEY (id);


--
-- Name: intelligence_reports intelligence_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_reports
    ADD CONSTRAINT intelligence_reports_pkey PRIMARY KEY (id);


--
-- Name: intent_edge intent_edge_from_intent_id_to_intent_id_relation_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intent_edge
    ADD CONSTRAINT intent_edge_from_intent_id_to_intent_id_relation_key UNIQUE (from_intent_id, to_intent_id, relation);


--
-- Name: intent_edge intent_edge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intent_edge
    ADD CONSTRAINT intent_edge_pkey PRIMARY KEY (edge_id);


--
-- Name: intent intent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intent
    ADD CONSTRAINT intent_pkey PRIMARY KEY (intent_id);


--
-- Name: interest_model interest_model_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.interest_model
    ADD CONSTRAINT interest_model_pkey PRIMARY KEY (user_id);


--
-- Name: interest_model_version interest_model_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.interest_model_version
    ADD CONSTRAINT interest_model_version_pkey PRIMARY KEY (id);


--
-- Name: ios_event_block ios_event_block_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ios_event_block
    ADD CONSTRAINT ios_event_block_pkey PRIMARY KEY (user_id, ios_event_id);


--
-- Name: jarvis_tasks jarvis_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jarvis_tasks
    ADD CONSTRAINT jarvis_tasks_pkey PRIMARY KEY (id);


--
-- Name: karma_agents karma_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_agents
    ADD CONSTRAINT karma_agents_pkey PRIMARY KEY (agent_id);


--
-- Name: karma_config karma_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_config
    ADD CONSTRAINT karma_config_pkey PRIMARY KEY (config_key);


--
-- Name: karma_dimensions karma_dimensions_agent_id_dimension_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_dimensions
    ADD CONSTRAINT karma_dimensions_agent_id_dimension_name_key UNIQUE (agent_id, dimension_name);


--
-- Name: karma_dimensions karma_dimensions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_dimensions
    ADD CONSTRAINT karma_dimensions_pkey PRIMARY KEY (dimension_id);


--
-- Name: karma_scores karma_scores_agent_id_dimension_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_scores
    ADD CONSTRAINT karma_scores_agent_id_dimension_name_key UNIQUE (agent_id, dimension_name);


--
-- Name: karma_scores karma_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_scores
    ADD CONSTRAINT karma_scores_pkey PRIMARY KEY (score_id);


--
-- Name: known_domain known_domain_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.known_domain
    ADD CONSTRAINT known_domain_pkey PRIMARY KEY (id);


--
-- Name: known_place known_place_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.known_place
    ADD CONSTRAINT known_place_pkey PRIMARY KEY (id);


--
-- Name: learning_artifact learning_artifact_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_artifact
    ADD CONSTRAINT learning_artifact_pkey PRIMARY KEY (id);


--
-- Name: learning_blueprint learning_blueprint_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_blueprint
    ADD CONSTRAINT learning_blueprint_pkey PRIMARY KEY (id);


--
-- Name: learning_guide_job learning_guide_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_guide_job
    ADD CONSTRAINT learning_guide_job_pkey PRIMARY KEY (id);


--
-- Name: learning_progress learning_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_progress
    ADD CONSTRAINT learning_progress_pkey PRIMARY KEY (id);


--
-- Name: learning_session learning_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_session
    ADD CONSTRAINT learning_session_pkey PRIMARY KEY (id);


--
-- Name: learning_topic learning_topic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_topic
    ADD CONSTRAINT learning_topic_pkey PRIMARY KEY (id);


--
-- Name: lesson_applications lesson_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesson_applications
    ADD CONSTRAINT lesson_applications_pkey PRIMARY KEY (id);


--
-- Name: life_fact life_fact_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.life_fact
    ADD CONSTRAINT life_fact_pkey PRIMARY KEY (id);


--
-- Name: list_item list_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_item
    ADD CONSTRAINT list_item_pkey PRIMARY KEY (id);


--
-- Name: live_activity_registration live_activity_registration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.live_activity_registration
    ADD CONSTRAINT live_activity_registration_pkey PRIMARY KEY (id);


--
-- Name: location_event location_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_event
    ADD CONSTRAINT location_event_pkey PRIMARY KEY (id);


--
-- Name: location_trigger location_trigger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_trigger
    ADD CONSTRAINT location_trigger_pkey PRIMARY KEY (id);


--
-- Name: machine machine_device_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine
    ADD CONSTRAINT machine_device_id_key UNIQUE (device_id);


--
-- Name: machine machine_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine
    ADD CONSTRAINT machine_pkey PRIMARY KEY (id);


--
-- Name: managed_host managed_host_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.managed_host
    ADD CONSTRAINT managed_host_pkey PRIMARY KEY (id);


--
-- Name: maps maps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maps
    ADD CONSTRAINT maps_pkey PRIMARY KEY (id);


--
-- Name: memory_edge memory_edge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_edge
    ADD CONSTRAINT memory_edge_pkey PRIMARY KEY (src, dst, type);


--
-- Name: memory_embedding memory_embedding_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_embedding
    ADD CONSTRAINT memory_embedding_pkey PRIMARY KEY (trace_id, head);


--
-- Name: memory_trace memory_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_trace
    ADD CONSTRAINT memory_trace_pkey PRIMARY KEY (id);


--
-- Name: ml_feature_daily ml_feature_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feature_daily
    ADD CONSTRAINT ml_feature_daily_pkey PRIMARY KEY (id);


--
-- Name: ml_model_version ml_model_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_model_version
    ADD CONSTRAINT ml_model_version_pkey PRIMARY KEY (id);


--
-- Name: ml_notification_outcome ml_notification_outcome_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_notification_outcome
    ADD CONSTRAINT ml_notification_outcome_pkey PRIMARY KEY (id);


--
-- Name: ml_prediction_log ml_prediction_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_prediction_log
    ADD CONSTRAINT ml_prediction_log_pkey PRIMARY KEY (id);


--
-- Name: models_3d models_3d_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.models_3d
    ADD CONSTRAINT models_3d_pkey PRIMARY KEY (id);


--
-- Name: moment_card moment_card_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moment_card
    ADD CONSTRAINT moment_card_pkey PRIMARY KEY (id);


--
-- Name: morning_brief morning_brief_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.morning_brief
    ADD CONSTRAINT morning_brief_pkey PRIMARY KEY (id);


--
-- Name: morning_readiness morning_readiness_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.morning_readiness
    ADD CONSTRAINT morning_readiness_pkey PRIMARY KEY (id);


--
-- Name: note_connection note_connection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_connection
    ADD CONSTRAINT note_connection_pkey PRIMARY KEY (id);


--
-- Name: note note_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note
    ADD CONSTRAINT note_pkey PRIMARY KEY (id);


--
-- Name: notification_log notification_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_log
    ADD CONSTRAINT notification_log_pkey PRIMARY KEY (id);


--
-- Name: notification_preference notification_preference_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_preference
    ADD CONSTRAINT notification_preference_pkey PRIMARY KEY (id);


--
-- Name: notification_queue notification_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_queue
    ADD CONSTRAINT notification_queue_pkey PRIMARY KEY (id);


--
-- Name: outbound_intent outbound_intent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_intent
    ADD CONSTRAINT outbound_intent_pkey PRIMARY KEY (outbound_intent_id);


--
-- Name: outbox_item outbox_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_item
    ADD CONSTRAINT outbox_item_pkey PRIMARY KEY (id);


--
-- Name: outbox_usage_log outbox_usage_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_usage_log
    ADD CONSTRAINT outbox_usage_log_pkey PRIMARY KEY (id);


--
-- Name: pattern_discovery_log pattern_discovery_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pattern_discovery_log
    ADD CONSTRAINT pattern_discovery_log_pkey PRIMARY KEY (id);


--
-- Name: pattern_suggestion_log pattern_suggestion_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pattern_suggestion_log
    ADD CONSTRAINT pattern_suggestion_log_pkey PRIMARY KEY (id);


--
-- Name: person person_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person
    ADD CONSTRAINT person_pkey PRIMARY KEY (id);


--
-- Name: person person_user_id_canonical_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person
    ADD CONSTRAINT person_user_id_canonical_name_key UNIQUE (user_id, canonical_name);


--
-- Name: pkg_embedding pkg_embedding_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pkg_embedding
    ADD CONSTRAINT pkg_embedding_pkey PRIMARY KEY (pkg_id);


--
-- Name: plan_templates plan_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_templates
    ADD CONSTRAINT plan_templates_pkey PRIMARY KEY (id);


--
-- Name: pr_task_link pr_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_task_link
    ADD CONSTRAINT pr_task_link_pkey PRIMARY KEY (id);


--
-- Name: prediction prediction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction
    ADD CONSTRAINT prediction_pkey PRIMARY KEY (id);


--
-- Name: presence_log presence_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.presence_log
    ADD CONSTRAINT presence_log_pkey PRIMARY KEY (id);


--
-- Name: privacy_settings privacy_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privacy_settings
    ADD CONSTRAINT privacy_settings_pkey PRIMARY KEY (user_id);


--
-- Name: progress_photo progress_photo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.progress_photo
    ADD CONSTRAINT progress_photo_pkey PRIMARY KEY (id);


--
-- Name: project_entity_link project_entity_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_entity_link
    ADD CONSTRAINT project_entity_link_pkey PRIMARY KEY (project_id, entity_type, entity_id);


--
-- Name: project_file project_file_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_file
    ADD CONSTRAINT project_file_pkey PRIMARY KEY (id);


--
-- Name: project_folder project_folder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_folder
    ADD CONSTRAINT project_folder_pkey PRIMARY KEY (id);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (id);


--
-- Name: promotion_event promotion_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotion_event
    ADD CONSTRAINT promotion_event_pkey PRIMARY KEY (id);


--
-- Name: prompt_proposals prompt_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_proposals
    ADD CONSTRAINT prompt_proposals_pkey PRIMARY KEY (proposal_id);


--
-- Name: prompt_versions prompt_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_versions
    ADD CONSTRAINT prompt_versions_pkey PRIMARY KEY (version_id);


--
-- Name: proxmox_container proxmox_container_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proxmox_container
    ADD CONSTRAINT proxmox_container_pkey PRIMARY KEY (id);


--
-- Name: proxmox_container proxmox_container_vmid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proxmox_container
    ADD CONSTRAINT proxmox_container_vmid_key UNIQUE (vmid);


--
-- Name: pull_request pull_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_request
    ADD CONSTRAINT pull_request_pkey PRIMARY KEY (id);


--
-- Name: push_token push_token_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_token
    ADD CONSTRAINT push_token_pkey PRIMARY KEY (id);


--
-- Name: push_token push_token_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_token
    ADD CONSTRAINT push_token_token_key UNIQUE (token);


--
-- Name: qa_checklist_item qa_checklist_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_checklist_item
    ADD CONSTRAINT qa_checklist_item_pkey PRIMARY KEY (id);


--
-- Name: qa_commit_result qa_commit_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_commit_result
    ADD CONSTRAINT qa_commit_result_pkey PRIMARY KEY (id);


--
-- Name: raw_buffer_stats raw_buffer_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_buffer_stats
    ADD CONSTRAINT raw_buffer_stats_pkey PRIMARY KEY (id);


--
-- Name: readiness_adjustments readiness_adjustments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_adjustments
    ADD CONSTRAINT readiness_adjustments_pkey PRIMARY KEY (id);


--
-- Name: readiness_baselines readiness_baselines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_baselines
    ADD CONSTRAINT readiness_baselines_pkey PRIMARY KEY (id);


--
-- Name: readiness_baselines readiness_baselines_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_baselines
    ADD CONSTRAINT readiness_baselines_user_id_key UNIQUE (user_id);


--
-- Name: reasoning_trace reasoning_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reasoning_trace
    ADD CONSTRAINT reasoning_trace_pkey PRIMARY KEY (id);


--
-- Name: recipe recipe_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recipe
    ADD CONSTRAINT recipe_pkey PRIMARY KEY (id);


--
-- Name: reflection_hypotheses reflection_hypotheses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_hypotheses
    ADD CONSTRAINT reflection_hypotheses_pkey PRIMARY KEY (hypothesis_id);


--
-- Name: reflection_observations reflection_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_observations
    ADD CONSTRAINT reflection_observations_pkey PRIMARY KEY (observation_id);


--
-- Name: reflection_patterns reflection_patterns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_patterns
    ADD CONSTRAINT reflection_patterns_pkey PRIMARY KEY (pattern_id);


--
-- Name: reflection_settings reflection_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_settings
    ADD CONSTRAINT reflection_settings_pkey PRIMARY KEY (user_id);


--
-- Name: registered_endpoint registered_endpoint_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registered_endpoint
    ADD CONSTRAINT registered_endpoint_name_key UNIQUE (name);


--
-- Name: registered_endpoint registered_endpoint_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registered_endpoint
    ADD CONSTRAINT registered_endpoint_pkey PRIMARY KEY (id);


--
-- Name: relationship_state relationship_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relationship_state
    ADD CONSTRAINT relationship_state_pkey PRIMARY KEY (id);


--
-- Name: reminder reminder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder
    ADD CONSTRAINT reminder_pkey PRIMARY KEY (id);


--
-- Name: research_brief research_brief_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_brief
    ADD CONSTRAINT research_brief_pkey PRIMARY KEY (id);


--
-- Name: research_job research_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_job
    ADD CONSTRAINT research_job_pkey PRIMARY KEY (id);


--
-- Name: research_message research_message_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_message
    ADD CONSTRAINT research_message_pkey PRIMARY KEY (id);


--
-- Name: research_plan research_plan_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_plan
    ADD CONSTRAINT research_plan_pkey PRIMARY KEY (id);


--
-- Name: research_report research_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_report
    ADD CONSTRAINT research_report_pkey PRIMARY KEY (id);


--
-- Name: sara_activity_log sara_activity_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_activity_log
    ADD CONSTRAINT sara_activity_log_pkey PRIMARY KEY (id);


--
-- Name: sara_commitment sara_commitment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_commitment
    ADD CONSTRAINT sara_commitment_pkey PRIMARY KEY (id);


--
-- Name: sara_daemon_state sara_daemon_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_daemon_state
    ADD CONSTRAINT sara_daemon_state_pkey PRIMARY KEY (id);


--
-- Name: sara_focus sara_focus_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_focus
    ADD CONSTRAINT sara_focus_pkey PRIMARY KEY (id);


--
-- Name: sara_goal sara_goal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_goal
    ADD CONSTRAINT sara_goal_pkey PRIMARY KEY (id);


--
-- Name: sara_inbox sara_inbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_inbox
    ADD CONSTRAINT sara_inbox_pkey PRIMARY KEY (id);


--
-- Name: sara_interest sara_interest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_interest
    ADD CONSTRAINT sara_interest_pkey PRIMARY KEY (id);


--
-- Name: sara_interest sara_interest_topic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_interest
    ADD CONSTRAINT sara_interest_topic_key UNIQUE (topic);


--
-- Name: sara_journal sara_journal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_journal
    ADD CONSTRAINT sara_journal_pkey PRIMARY KEY (id);


--
-- Name: sara_presence_snapshot sara_presence_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_presence_snapshot
    ADD CONSTRAINT sara_presence_snapshot_pkey PRIMARY KEY (user_id);


--
-- Name: sara_reflection sara_reflection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_reflection
    ADD CONSTRAINT sara_reflection_pkey PRIMARY KEY (id);


--
-- Name: sara_soul sara_soul_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_soul
    ADD CONSTRAINT sara_soul_pkey PRIMARY KEY (id);


--
-- Name: sara_soul sara_soul_section_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_soul
    ADD CONSTRAINT sara_soul_section_key UNIQUE (section);


--
-- Name: sara_tool_invocation sara_tool_invocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_invocation
    ADD CONSTRAINT sara_tool_invocation_pkey PRIMARY KEY (id);


--
-- Name: sara_tool sara_tool_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool
    ADD CONSTRAINT sara_tool_name_key UNIQUE (name);


--
-- Name: sara_tool sara_tool_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool
    ADD CONSTRAINT sara_tool_pkey PRIMARY KEY (id);


--
-- Name: sara_tool_version sara_tool_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_version
    ADD CONSTRAINT sara_tool_version_pkey PRIMARY KEY (id);


--
-- Name: sara_tool_version sara_tool_version_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_version
    ADD CONSTRAINT sara_tool_version_unique UNIQUE (tool_id, version);


--
-- Name: saved_meal saved_meal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_meal
    ADD CONSTRAINT saved_meal_pkey PRIMARY KEY (id);


--
-- Name: say_candidate say_candidate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.say_candidate
    ADD CONSTRAINT say_candidate_pkey PRIMARY KEY (id);


--
-- Name: scheduled_home_action scheduled_home_action_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_home_action
    ADD CONSTRAINT scheduled_home_action_pkey PRIMARY KEY (id);


--
-- Name: scheduled_job scheduled_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_job
    ADD CONSTRAINT scheduled_job_pkey PRIMARY KEY (key);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (name);


--
-- Name: scratchpad_entry scratchpad_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scratchpad_entry
    ADD CONSTRAINT scratchpad_entry_pkey PRIMARY KEY (id);


--
-- Name: semantic_summary semantic_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.semantic_summary
    ADD CONSTRAINT semantic_summary_pkey PRIMARY KEY (id);


--
-- Name: shadow_event shadow_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_event
    ADD CONSTRAINT shadow_event_pkey PRIMARY KEY (id);


--
-- Name: shadow_note shadow_note_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_note
    ADD CONSTRAINT shadow_note_pkey PRIMARY KEY (id);


--
-- Name: shadow_screenshot shadow_screenshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_screenshot
    ADD CONSTRAINT shadow_screenshot_pkey PRIMARY KEY (id);


--
-- Name: shadow_session shadow_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_session
    ADD CONSTRAINT shadow_session_pkey PRIMARY KEY (id);


--
-- Name: shadow_summary shadow_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_summary
    ADD CONSTRAINT shadow_summary_pkey PRIMARY KEY (id);


--
-- Name: shadow_summary shadow_summary_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_summary
    ADD CONSTRAINT shadow_summary_session_id_key UNIQUE (session_id);


--
-- Name: shared_content shared_content_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_content
    ADD CONSTRAINT shared_content_pkey PRIMARY KEY (id);


--
-- Name: signal_baseline signal_baseline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_baseline
    ADD CONSTRAINT signal_baseline_pkey PRIMARY KEY (id);


--
-- Name: signal_baseline signal_baseline_user_id_domain_signal_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_baseline
    ADD CONSTRAINT signal_baseline_user_id_domain_signal_key_key UNIQUE (user_id, domain, signal_key);


--
-- Name: singular_context_turn_log singular_context_turn_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.singular_context_turn_log
    ADD CONSTRAINT singular_context_turn_log_pkey PRIMARY KEY (id);


--
-- Name: soul_change_proposals soul_change_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.soul_change_proposals
    ADD CONSTRAINT soul_change_proposals_pkey PRIMARY KEY (id);


--
-- Name: source_chunk source_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunk
    ADD CONSTRAINT source_chunk_pkey PRIMARY KEY (id);


--
-- Name: standing_order standing_order_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.standing_order
    ADD CONSTRAINT standing_order_pkey PRIMARY KEY (id);


--
-- Name: stimulus_habituation stimulus_habituation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stimulus_habituation
    ADD CONSTRAINT stimulus_habituation_pkey PRIMARY KEY (id);


--
-- Name: subconscious_log subconscious_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subconscious_log
    ADD CONSTRAINT subconscious_log_pkey PRIMARY KEY (id);


--
-- Name: subconscious_nudge subconscious_nudge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subconscious_nudge
    ADD CONSTRAINT subconscious_nudge_pkey PRIMARY KEY (id);


--
-- Name: subconscious_state subconscious_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subconscious_state
    ADD CONSTRAINT subconscious_state_pkey PRIMARY KEY (id);


--
-- Name: subconscious_state subconscious_state_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subconscious_state
    ADD CONSTRAINT subconscious_state_user_id_key UNIQUE (user_id);


--
-- Name: surface surface_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.surface
    ADD CONSTRAINT surface_pkey PRIMARY KEY (id);


--
-- Name: system_event system_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_event
    ADD CONSTRAINT system_event_pkey PRIMARY KEY (id);


--
-- Name: tabata_preset tabata_preset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tabata_preset
    ADD CONSTRAINT tabata_preset_pkey PRIMARY KEY (id);


--
-- Name: tangent_queue tangent_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tangent_queue
    ADD CONSTRAINT tangent_queue_pkey PRIMARY KEY (id);


--
-- Name: task_commit_link task_commit_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_commit_link
    ADD CONSTRAINT task_commit_link_pkey PRIMARY KEY (id);


--
-- Name: task_failure task_failure_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_failure
    ADD CONSTRAINT task_failure_pkey PRIMARY KEY (id);


--
-- Name: task_item task_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_item
    ADD CONSTRAINT task_item_pkey PRIMARY KEY (id);


--
-- Name: temerant_attribute_state temerant_attribute_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_attribute_state
    ADD CONSTRAINT temerant_attribute_state_pkey PRIMARY KEY (id);


--
-- Name: temerant_character temerant_character_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_character
    ADD CONSTRAINT temerant_character_pkey PRIMARY KEY (id);


--
-- Name: temerant_character temerant_character_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_character
    ADD CONSTRAINT temerant_character_user_id_key UNIQUE (user_id);


--
-- Name: temerant_daily_state temerant_daily_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_daily_state
    ADD CONSTRAINT temerant_daily_state_pkey PRIMARY KEY (id);


--
-- Name: temerant_ingestion_cursor temerant_ingestion_cursor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_ingestion_cursor
    ADD CONSTRAINT temerant_ingestion_cursor_pkey PRIMARY KEY (id);


--
-- Name: temerant_journal_entry temerant_journal_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_journal_entry
    ADD CONSTRAINT temerant_journal_entry_pkey PRIMARY KEY (id);


--
-- Name: temerant_mapping_rule temerant_mapping_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_mapping_rule
    ADD CONSTRAINT temerant_mapping_rule_pkey PRIMARY KEY (id);


--
-- Name: temerant_masterwork temerant_masterwork_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_masterwork
    ADD CONSTRAINT temerant_masterwork_pkey PRIMARY KEY (id);


--
-- Name: temerant_oracle_event temerant_oracle_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_oracle_event
    ADD CONSTRAINT temerant_oracle_event_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_character temerant_rpg_character_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_character
    ADD CONSTRAINT temerant_rpg_character_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_character temerant_rpg_character_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_character
    ADD CONSTRAINT temerant_rpg_character_user_id_key UNIQUE (user_id);


--
-- Name: temerant_rpg_journal_entry temerant_rpg_journal_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_journal_entry
    ADD CONSTRAINT temerant_rpg_journal_entry_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_relationship temerant_rpg_relationship_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_relationship
    ADD CONSTRAINT temerant_rpg_relationship_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_scene temerant_rpg_scene_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene
    ADD CONSTRAINT temerant_rpg_scene_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_scene_turn temerant_rpg_scene_turn_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene_turn
    ADD CONSTRAINT temerant_rpg_scene_turn_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_term temerant_rpg_term_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_term
    ADD CONSTRAINT temerant_rpg_term_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_world_state temerant_rpg_world_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_world_state
    ADD CONSTRAINT temerant_rpg_world_state_pkey PRIMARY KEY (id);


--
-- Name: temerant_rpg_world_state temerant_rpg_world_state_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_world_state
    ADD CONSTRAINT temerant_rpg_world_state_user_id_key UNIQUE (user_id);


--
-- Name: temerant_story_thread temerant_story_thread_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_story_thread
    ADD CONSTRAINT temerant_story_thread_pkey PRIMARY KEY (id);


--
-- Name: temerant_term temerant_term_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_term
    ADD CONSTRAINT temerant_term_pkey PRIMARY KEY (id);


--
-- Name: temerant_xp_ledger temerant_xp_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_xp_ledger
    ADD CONSTRAINT temerant_xp_ledger_pkey PRIMARY KEY (id);


--
-- Name: template_exercise template_exercise_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_exercise
    ADD CONSTRAINT template_exercise_pkey PRIMARY KEY (id);


--
-- Name: temporal_bin temporal_bin_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temporal_bin
    ADD CONSTRAINT temporal_bin_pkey PRIMARY KEY (id);


--
-- Name: timer timer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timer
    ADD CONSTRAINT timer_pkey PRIMARY KEY (id);


--
-- Name: token_usage_aggregate token_usage_aggregate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage_aggregate
    ADD CONSTRAINT token_usage_aggregate_pkey PRIMARY KEY (id);


--
-- Name: token_usage token_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT token_usage_pkey PRIMARY KEY (id);


--
-- Name: topic_connection topic_connection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_connection
    ADD CONSTRAINT topic_connection_pkey PRIMARY KEY (id);


--
-- Name: topic_scratchpad topic_scratchpad_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_scratchpad
    ADD CONSTRAINT topic_scratchpad_pkey PRIMARY KEY (id);


--
-- Name: topic_scratchpad topic_scratchpad_topic_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_scratchpad
    ADD CONSTRAINT topic_scratchpad_topic_id_user_id_key UNIQUE (topic_id, user_id);


--
-- Name: topic_source topic_source_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_source
    ADD CONSTRAINT topic_source_pkey PRIMARY KEY (id);


--
-- Name: truth_maintenance_report truth_maintenance_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.truth_maintenance_report
    ADD CONSTRAINT truth_maintenance_report_pkey PRIMARY KEY (id);


--
-- Name: tunable_setting tunable_setting_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tunable_setting
    ADD CONSTRAINT tunable_setting_pkey PRIMARY KEY (key);


--
-- Name: automation_state_store uq_automation_state_task_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_state_store
    ADD CONSTRAINT uq_automation_state_task_key UNIQUE (task_id, key);


--
-- Name: daily_rhythm uq_daily_rhythm_user_key_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_rhythm
    ADD CONSTRAINT uq_daily_rhythm_user_key_scope UNIQUE (user_id, rhythm_key, day_scope);


--
-- Name: day_type_override uq_day_type_override; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_type_override
    ADD CONSTRAINT uq_day_type_override UNIQUE (user_id, override_date);


--
-- Name: health_weekly_report uq_hwr_user_week; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_weekly_report
    ADD CONSTRAINT uq_hwr_user_week UNIQUE (user_id, week_start);


--
-- Name: known_domain uq_known_domain_user_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.known_domain
    ADD CONSTRAINT uq_known_domain_user_name UNIQUE (user_id, domain_name);


--
-- Name: life_fact uq_life_fact_user_predicate_weekday; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.life_fact
    ADD CONSTRAINT uq_life_fact_user_predicate_weekday UNIQUE (user_id, predicate, weekday);


--
-- Name: live_activity_registration uq_live_activity_user_activity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.live_activity_registration
    ADD CONSTRAINT uq_live_activity_user_activity UNIQUE (user_id, activity_id);


--
-- Name: ml_feature_daily uq_ml_feature_daily_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feature_daily
    ADD CONSTRAINT uq_ml_feature_daily_user_date UNIQUE (user_id, feature_date);


--
-- Name: ml_model_version uq_ml_model_version_family_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_model_version
    ADD CONSTRAINT uq_ml_model_version_family_version UNIQUE (family, version);


--
-- Name: pr_task_link uq_pr_task; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_task_link
    ADD CONSTRAINT uq_pr_task UNIQUE (pr_id, task_id);


--
-- Name: qa_commit_result uq_qa_commit_result_commit; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_commit_result
    ADD CONSTRAINT uq_qa_commit_result_commit UNIQUE (commit_id);


--
-- Name: research_brief uq_research_brief_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_brief
    ADD CONSTRAINT uq_research_brief_user_date UNIQUE (user_id, brief_date);


--
-- Name: stimulus_habituation uq_stimulus_habituation_generator_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stimulus_habituation
    ADD CONSTRAINT uq_stimulus_habituation_generator_key UNIQUE (generator, stimulus_key);


--
-- Name: task_commit_link uq_task_commit; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_commit_link
    ADD CONSTRAINT uq_task_commit UNIQUE (task_id, commit_id);


--
-- Name: task_failure uq_task_failure_task_error; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_failure
    ADD CONSTRAINT uq_task_failure_task_error UNIQUE (task_name, error_class);


--
-- Name: temerant_attribute_state uq_temerant_attribute_state_character_attr; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_attribute_state
    ADD CONSTRAINT uq_temerant_attribute_state_character_attr UNIQUE (character_id, attribute);


--
-- Name: temerant_daily_state uq_temerant_daily_state_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_daily_state
    ADD CONSTRAINT uq_temerant_daily_state_user_date UNIQUE (user_id, local_date);


--
-- Name: temerant_ingestion_cursor uq_temerant_ingestion_cursor_user_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_ingestion_cursor
    ADD CONSTRAINT uq_temerant_ingestion_cursor_user_source UNIQUE (user_id, source_type);


--
-- Name: temerant_journal_entry uq_temerant_journal_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_journal_entry
    ADD CONSTRAINT uq_temerant_journal_user_date UNIQUE (user_id, local_date);


--
-- Name: temerant_xp_ledger uq_temerant_ledger_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_xp_ledger
    ADD CONSTRAINT uq_temerant_ledger_idempotency UNIQUE (idempotency_key);


--
-- Name: temerant_rpg_journal_entry uq_temerant_rpg_journal_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_journal_entry
    ADD CONSTRAINT uq_temerant_rpg_journal_user_date UNIQUE (user_id, local_date);


--
-- Name: temerant_rpg_relationship uq_temerant_rpg_relationship_character_npc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_relationship
    ADD CONSTRAINT uq_temerant_rpg_relationship_character_npc UNIQUE (character_id, npc_key);


--
-- Name: temerant_rpg_term uq_temerant_rpg_term_user_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_term
    ADD CONSTRAINT uq_temerant_rpg_term_user_index UNIQUE (user_id, term_index);


--
-- Name: temerant_term uq_temerant_term_user_month; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_term
    ADD CONSTRAINT uq_temerant_term_user_month UNIQUE (user_id, term_month);


--
-- Name: topic_connection uq_topic_connection_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_connection
    ADD CONSTRAINT uq_topic_connection_pair UNIQUE (user_id, source_topic_id, target_topic_id, connection_type);


--
-- Name: weight_trend uq_weight_trend_user_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weight_trend
    ADD CONSTRAINT uq_weight_trend_user_date UNIQUE (user_id, date);


--
-- Name: world_attention_item uq_world_attention_coalesce; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_attention_item
    ADD CONSTRAINT uq_world_attention_coalesce UNIQUE (user_id, coalesce_key);


--
-- Name: world_entity uq_world_entity_canonical; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_entity
    ADD CONSTRAINT uq_world_entity_canonical UNIQUE (user_id, kind, canonical_key);


--
-- Name: world_event uq_world_event_user_dedupe; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event
    ADD CONSTRAINT uq_world_event_user_dedupe UNIQUE (user_id, dedupe_key);


--
-- Name: world_thread uq_world_thread_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_thread
    ADD CONSTRAINT uq_world_thread_key UNIQUE (user_id, thread_key);


--
-- Name: user_activity_log user_activity_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_activity_log
    ADD CONSTRAINT user_activity_log_pkey PRIMARY KEY (id);


--
-- Name: user_life_context user_life_context_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_life_context
    ADD CONSTRAINT user_life_context_pkey PRIMARY KEY (id);


--
-- Name: user_profile user_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profile
    ADD CONSTRAINT user_profile_pkey PRIMARY KEY (id);


--
-- Name: user_profile user_profile_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profile
    ADD CONSTRAINT user_profile_user_id_key UNIQUE (user_id);


--
-- Name: user_relationship user_relationship_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_relationship
    ADD CONSTRAINT user_relationship_pkey PRIMARY KEY (user_id);


--
-- Name: user_settings user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_pkey PRIMARY KEY (id);


--
-- Name: user_settings user_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_key UNIQUE (user_id);


--
-- Name: voice_interaction_log voice_interaction_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_interaction_log
    ADD CONSTRAINT voice_interaction_log_pkey PRIMARY KEY (id);


--
-- Name: weight_trend weight_trend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weight_trend
    ADD CONSTRAINT weight_trend_pkey PRIMARY KEY (id);


--
-- Name: workout_adjustment_proposal workout_adjustment_proposal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_adjustment_proposal
    ADD CONSTRAINT workout_adjustment_proposal_pkey PRIMARY KEY (id);


--
-- Name: workout_approved_policy workout_approved_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_approved_policy
    ADD CONSTRAINT workout_approved_policy_pkey PRIMARY KEY (user_id);


--
-- Name: workout_log workout_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT workout_log_pkey PRIMARY KEY (id);


--
-- Name: workout workout_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout
    ADD CONSTRAINT workout_pkey PRIMARY KEY (id);


--
-- Name: workout_session_command workout_session_command_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_session_command
    ADD CONSTRAINT workout_session_command_pkey PRIMARY KEY (command_id);


--
-- Name: workout_session_event workout_session_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_session_event
    ADD CONSTRAINT workout_session_event_pkey PRIMARY KEY (id);


--
-- Name: workout_session workout_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_session
    ADD CONSTRAINT workout_session_pkey PRIMARY KEY (id);


--
-- Name: workspace_job workspace_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_job
    ADD CONSTRAINT workspace_job_pkey PRIMARY KEY (id);


--
-- Name: workspace_states workspace_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_states
    ADD CONSTRAINT workspace_states_pkey PRIMARY KEY (id);


--
-- Name: workspace_states workspace_states_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_states
    ADD CONSTRAINT workspace_states_user_id_key UNIQUE (user_id);


--
-- Name: world_attention_item world_attention_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_attention_item
    ADD CONSTRAINT world_attention_item_pkey PRIMARY KEY (id);


--
-- Name: world_brief_patch_log world_brief_patch_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_brief_patch_log
    ADD CONSTRAINT world_brief_patch_log_pkey PRIMARY KEY (id);


--
-- Name: world_brief world_brief_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_brief
    ADD CONSTRAINT world_brief_pkey PRIMARY KEY (user_id);


--
-- Name: world_entity world_entity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_entity
    ADD CONSTRAINT world_entity_pkey PRIMARY KEY (id);


--
-- Name: world_event_disposition world_event_disposition_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_disposition
    ADD CONSTRAINT world_event_disposition_event_id_key UNIQUE (event_id);


--
-- Name: world_event_disposition world_event_disposition_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_disposition
    ADD CONSTRAINT world_event_disposition_pkey PRIMARY KEY (id);


--
-- Name: world_event world_event_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event
    ADD CONSTRAINT world_event_event_id_key UNIQUE (event_id);


--
-- Name: world_event world_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event
    ADD CONSTRAINT world_event_pkey PRIMARY KEY (sequence);


--
-- Name: world_event_processing world_event_processing_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_processing
    ADD CONSTRAINT world_event_processing_event_id_key UNIQUE (event_id);


--
-- Name: world_event_processing world_event_processing_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_processing
    ADD CONSTRAINT world_event_processing_pkey PRIMARY KEY (id);


--
-- Name: world_fact world_fact_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_fact
    ADD CONSTRAINT world_fact_pkey PRIMARY KEY (id);


--
-- Name: world_snapshot world_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_snapshot
    ADD CONSTRAINT world_snapshot_pkey PRIMARY KEY (user_id);


--
-- Name: world_thread world_thread_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_thread
    ADD CONSTRAINT world_thread_pkey PRIMARY KEY (id);


--
-- Name: idx_achievement_celebrated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_achievement_celebrated ON public.achievement USING btree (user_id, celebrated) WHERE (celebrated = false);


--
-- Name: idx_achievement_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_achievement_type ON public.achievement USING btree (user_id, type);


--
-- Name: idx_achievement_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_achievement_user ON public.achievement USING btree (user_id, earned_at DESC);


--
-- Name: idx_action_ledger_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_ledger_order ON public.action_ledger USING btree (standing_order_id, executed_at DESC);


--
-- Name: idx_action_ledger_undo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_ledger_undo ON public.action_ledger USING btree (undo_available, undo_expires_at) WHERE ((undo_available = true) AND (undone = false));


--
-- Name: idx_action_log_outcome; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_log_outcome ON public.action_log USING btree (outcome_status, created_at DESC);


--
-- Name: idx_action_log_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_log_type ON public.action_log USING btree (action_type, created_at DESC);


--
-- Name: idx_action_log_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_log_user_time ON public.action_log USING btree (user_id, created_at DESC);


--
-- Name: idx_action_receipt_ledger_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_receipt_ledger_id ON public.action_receipt USING btree (ledger_id) WHERE (ledger_id IS NOT NULL);


--
-- Name: idx_action_receipt_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_receipt_source ON public.action_receipt USING btree (source_table, source_id);


--
-- Name: idx_action_receipt_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_receipt_status ON public.action_receipt USING btree (status);


--
-- Name: idx_action_receipt_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_receipt_user ON public.action_receipt USING btree (user_id, created_at DESC);


--
-- Name: idx_action_trace_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_action_trace_idempotency ON public.autonomy_action_trace USING btree (idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: idx_action_trace_run_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_trace_run_uuid ON public.autonomy_action_trace USING btree (run_uuid);


--
-- Name: idx_action_trace_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_trace_user_created ON public.autonomy_action_trace USING btree (user_id, created_at DESC);


--
-- Name: idx_agent_run_log_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_log_recent ON public.agent_run_log USING btree (run_at DESC);


--
-- Name: idx_agent_run_log_user_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_log_user_run_at ON public.agent_run_log USING btree (user_id, run_at DESC);


--
-- Name: idx_anchor_point_topic_validated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_anchor_point_topic_validated ON public.anchor_point USING btree (topic_id, validated);


--
-- Name: idx_app_user_role_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_app_user_role_role ON public.app_user_role USING btree (role);


--
-- Name: idx_attention_item_outbound; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attention_item_outbound ON public.attention_item USING btree (outbound_intent_id);


--
-- Name: idx_automation_log_task_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_log_task_started ON public.automation_execution_log USING btree (task_id, started_at DESC);


--
-- Name: idx_automation_state_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_state_task_id ON public.automation_state_store USING btree (task_id);


--
-- Name: idx_automation_task_next_wake; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_task_next_wake ON public.automation_task USING btree (next_wake_at, status);


--
-- Name: idx_automation_task_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_task_status ON public.automation_task USING btree (status);


--
-- Name: idx_automation_task_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_task_user_id ON public.automation_task USING btree (user_id);


--
-- Name: idx_automation_task_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_automation_task_user_status ON public.automation_task USING btree (user_id, status);


--
-- Name: idx_behavioral_pattern_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_behavioral_pattern_category ON public.behavioral_pattern USING btree (user_id, category, status);


--
-- Name: idx_behavioral_pattern_trigger; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_behavioral_pattern_trigger ON public.behavioral_pattern USING btree (trigger_type, status);


--
-- Name: idx_behavioral_pattern_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_behavioral_pattern_user_status ON public.behavioral_pattern USING btree (user_id, status);


--
-- Name: idx_body_capability_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_body_capability_kind ON public.body_capability USING btree (kind);


--
-- Name: idx_brief_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brief_date ON public.daily_briefs USING btree (brief_date);


--
-- Name: idx_brief_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brief_user_date ON public.daily_briefs USING btree (user_id, brief_date);


--
-- Name: idx_calendar_event_start_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calendar_event_start_time ON public.calendar_event USING btree (start_time);


--
-- Name: idx_calendar_event_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calendar_event_user_id ON public.calendar_event USING btree (user_id);


--
-- Name: idx_calibration_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibration_type ON public.body_state_calibration USING btree (estimate_type);


--
-- Name: idx_calibration_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibration_user ON public.body_state_calibration USING btree (user_id);


--
-- Name: idx_candidate_skill_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_skill_status ON public.candidate_skill USING btree (status);


--
-- Name: idx_candidate_skill_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_skill_user_id ON public.candidate_skill USING btree (user_id);


--
-- Name: idx_cardio_log_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cardio_log_user_date ON public.cardio_log USING btree (user_id, session_date DESC);


--
-- Name: idx_cardio_log_user_logged; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cardio_log_user_logged ON public.cardio_log USING btree (user_id, logged_at DESC);


--
-- Name: idx_composed_utterance_candidate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_composed_utterance_candidate ON public.composed_utterance USING btree (candidate_id);


--
-- Name: idx_composed_utterance_undelivered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_composed_utterance_undelivered ON public.composed_utterance USING btree (created_at) WHERE ((delivered_at IS NULL) AND ((review_verdict)::text = ANY ((ARRAY['approve'::character varying, 'edit'::character varying])::text[])));


--
-- Name: idx_composed_utterance_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_composed_utterance_user_created ON public.composed_utterance USING btree (user_id, created_at);


--
-- Name: idx_consolidation_config_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consolidation_config_user ON public.consolidation_config USING btree (user_id);


--
-- Name: idx_consolidation_discards_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consolidation_discards_run ON public.consolidation_discards USING btree (consolidation_run_id);


--
-- Name: idx_consolidation_discards_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consolidation_discards_time ON public.consolidation_discards USING btree (created_at DESC);


--
-- Name: idx_consolidation_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consolidation_runs_status ON public.consolidation_runs USING btree (status);


--
-- Name: idx_consolidation_runs_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consolidation_runs_user_time ON public.consolidation_runs USING btree (user_id, started_at DESC);


--
-- Name: idx_day_replay_cache_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_day_replay_cache_lookup ON public.day_replay_cache USING btree (user_id, replay_date DESC);


--
-- Name: idx_dream_insight_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_insight_embedding ON public.dream_insight USING hnsw (embedding public.vector_l2_ops);


--
-- Name: idx_dream_insight_surface; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_insight_surface ON public.dream_insight USING btree (user_id, surface_strategy, surfaced_count);


--
-- Name: idx_email_attachment_email_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_attachment_email_id ON public.email_attachment USING btree (email_id);


--
-- Name: idx_email_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_category ON public.email USING btree (category);


--
-- Name: idx_email_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_conversation_id ON public.email USING btree (conversation_id);


--
-- Name: idx_email_mailbox; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_mailbox ON public.email USING btree (mailbox);


--
-- Name: idx_email_received_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_received_at ON public.email USING btree (received_at);


--
-- Name: idx_email_sender_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_sender_email ON public.email USING btree (sender_email);


--
-- Name: idx_email_sync_state_user_mailbox; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_sync_state_user_mailbox ON public.email_sync_state USING btree (user_id, mailbox);


--
-- Name: idx_email_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_user_id ON public.email USING btree (user_id);


--
-- Name: idx_entity_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_project ON public.project_entity_link USING btree (entity_type, entity_id);


--
-- Name: idx_episode_exploration_bonus; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episode_exploration_bonus ON public.episode USING btree (exploration_bonus);


--
-- Name: idx_episode_rating_boost; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episode_rating_boost ON public.episode USING btree (rating_boost);


--
-- Name: idx_episode_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episode_thread ON public.episode_thread_mapping USING btree (thread_id);


--
-- Name: idx_episode_user_created_rating; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episode_user_created_rating ON public.episode USING btree (user_id, created_at, rating_boost);


--
-- Name: idx_fitness_daily_log_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_daily_log_date ON public.fitness_daily_log USING btree (log_date DESC);


--
-- Name: idx_fitness_daily_log_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_daily_log_user_date ON public.fitness_daily_log USING btree (user_id, log_date DESC);


--
-- Name: idx_fitness_phase_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_phase_dates ON public.fitness_phase USING btree (start_date, end_date);


--
-- Name: idx_fitness_phase_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_phase_user ON public.fitness_phase USING btree (user_id, status);


--
-- Name: idx_fitness_settings_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_settings_user ON public.fitness_settings USING btree (user_id);


--
-- Name: idx_fitness_template_phase; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_template_phase ON public.fitness_template USING btree (phase_id);


--
-- Name: idx_fitness_template_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fitness_template_user ON public.fitness_template USING btree (user_id);


--
-- Name: idx_followup_thread_user_open; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_thread_user_open ON public.followup_thread USING btree (user_id, status) WHERE ((status)::text = 'open'::text);


--
-- Name: idx_followup_thread_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_thread_window ON public.followup_thread USING btree (follow_up_after, follow_up_before) WHERE ((status)::text = 'open'::text);


--
-- Name: idx_food_database_barcode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_food_database_barcode ON public.food_database USING btree (barcode) WHERE (barcode IS NOT NULL);


--
-- Name: idx_food_database_user_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_food_database_user_name ON public.food_database USING btree (user_id, name);


--
-- Name: idx_food_log_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_food_log_idempotency_key ON public.food_log USING btree (user_id, idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: idx_gtky_sessions_pack; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gtky_sessions_pack ON public.gtky_sessions USING btree (question_pack);


--
-- Name: idx_gtky_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gtky_sessions_user_id ON public.gtky_sessions USING btree (user_id);


--
-- Name: idx_heartbeat_items_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_heartbeat_items_active ON public.heartbeat_items USING btree (user_id, is_active);


--
-- Name: idx_heartbeat_items_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_heartbeat_items_type ON public.heartbeat_items USING btree (item_type);


--
-- Name: idx_heartbeat_items_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_heartbeat_items_user ON public.heartbeat_items USING btree (user_id);


--
-- Name: idx_heartbeat_logs_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_heartbeat_logs_run_at ON public.heartbeat_logs USING btree (run_at DESC);


--
-- Name: idx_heartbeat_logs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_heartbeat_logs_user ON public.heartbeat_logs USING btree (user_id);


--
-- Name: idx_home_activity_changed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_home_activity_changed_at ON public.home_activity_log USING btree (changed_at);


--
-- Name: idx_home_activity_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_home_activity_domain ON public.home_activity_log USING btree (domain, changed_at);


--
-- Name: idx_home_activity_entity_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_home_activity_entity_time ON public.home_activity_log USING btree (entity_id, changed_at);


--
-- Name: idx_home_state_summary_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_home_state_summary_unique ON public.home_state_summary USING btree (user_id, hour_bucket);


--
-- Name: idx_home_state_summary_user_hour; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_home_state_summary_user_hour ON public.home_state_summary USING btree (user_id, hour_bucket DESC);


--
-- Name: idx_insight_mention_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insight_mention_conversation ON public.insight_mention_log USING btree (conversation_id);


--
-- Name: idx_insight_mention_insight; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insight_mention_insight ON public.insight_mention_log USING btree (insight_id);


--
-- Name: idx_insight_mention_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insight_mention_user ON public.insight_mention_log USING btree (user_id, mentioned_at);


--
-- Name: idx_intent_edge_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intent_edge_from ON public.intent_edge USING btree (from_intent_id);


--
-- Name: idx_intent_edge_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intent_edge_to ON public.intent_edge USING btree (to_intent_id);


--
-- Name: idx_intent_next_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intent_next_review ON public.intent USING btree (next_review_at) WHERE (next_review_at IS NOT NULL);


--
-- Name: idx_intent_owner_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intent_owner_status ON public.intent USING btree (owner_user_id, status);


--
-- Name: idx_intent_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intent_source ON public.intent USING btree (source_table, source_id);


--
-- Name: idx_interest_model_version_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_interest_model_version_user ON public.interest_model_version USING btree (user_id, version);


--
-- Name: idx_karma_scores_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_karma_scores_agent ON public.karma_scores USING btree (agent_id);


--
-- Name: idx_known_domain_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_known_domain_user ON public.known_domain USING btree (user_id);


--
-- Name: idx_lesson_applications_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lesson_applications_conversation ON public.lesson_applications USING btree (conversation_id);


--
-- Name: idx_lesson_applications_lesson; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lesson_applications_lesson ON public.lesson_applications USING btree (lesson_id, created_at DESC);


--
-- Name: idx_lesson_applications_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lesson_applications_recent ON public.lesson_applications USING btree (created_at DESC) WHERE ((outcome)::text <> 'unknown'::text);


--
-- Name: idx_list_item_user_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_list_item_user_list ON public.list_item USING btree (user_id, list_name, checked);


--
-- Name: idx_maps_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maps_name ON public.maps USING btree (name);


--
-- Name: idx_maps_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maps_user_id ON public.maps USING btree (user_id);


--
-- Name: idx_mission_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mission_active ON public.autonomy_mission USING btree (state, updated_at) WHERE ((state)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'awaiting_confirm'::character varying])::text[]));


--
-- Name: idx_mission_step_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mission_step_status ON public.autonomy_mission_step USING btree (mission_id, status);


--
-- Name: idx_mission_step_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_mission_step_unique ON public.autonomy_mission_step USING btree (mission_id, step_index);


--
-- Name: idx_mission_user_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mission_user_state ON public.autonomy_mission USING btree (user_id, state, created_at DESC);


--
-- Name: idx_models_3d_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_models_3d_user_id ON public.models_3d USING btree (user_id);


--
-- Name: idx_moment_card_kind_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_moment_card_kind_created ON public.moment_card USING btree (user_id, kind, created_at DESC);


--
-- Name: idx_moment_card_user_unseen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_moment_card_user_unseen ON public.moment_card USING btree (user_id, created_at DESC) WHERE ((seen_at IS NULL) AND (dismissed_at IS NULL));


--
-- Name: idx_notification_log_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_log_category ON public.notification_log USING btree (user_id, category, sent_at DESC);


--
-- Name: idx_notification_log_suppress_reason; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_log_suppress_reason ON public.notification_log USING btree (user_id, suppress_reason, sent_at) WHERE (suppress_reason IS NOT NULL);


--
-- Name: idx_notification_log_today; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_log_today ON public.notification_log USING btree (user_id, sent_at DESC);


--
-- Name: idx_notification_log_topic_dedup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_log_topic_dedup ON public.notification_log USING btree (user_id, topic, sent_at DESC);


--
-- Name: idx_notification_queue_user_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_queue_user_pending ON public.notification_queue USING btree (user_id, was_delivered, deliver_by) WHERE (was_delivered = false);


--
-- Name: idx_outbound_intent_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbound_intent_user ON public.outbound_intent USING btree (user_id, created_at DESC);


--
-- Name: idx_outbox_dedupe; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_outbox_dedupe ON public.outbox_item USING btree (user_id, dedupe_key) WHERE ((dedupe_key IS NOT NULL) AND ((status)::text = ANY ((ARRAY['new'::character varying, 'sent'::character varying])::text[])));


--
-- Name: idx_outbox_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbox_priority ON public.outbox_item USING btree (user_id, priority, created_at DESC) WHERE ((status)::text = ANY ((ARRAY['new'::character varying, 'sent'::character varying])::text[]));


--
-- Name: idx_outbox_usage_log_kind_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbox_usage_log_kind_created ON public.outbox_usage_log USING btree (kind, created_at DESC);


--
-- Name: idx_outbox_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbox_user_status ON public.outbox_item USING btree (user_id, status, created_at DESC);


--
-- Name: idx_pattern_suggestion_log_pattern; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pattern_suggestion_log_pattern ON public.pattern_suggestion_log USING btree (pattern_id, suggested_at DESC);


--
-- Name: idx_pattern_suggestion_log_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pattern_suggestion_log_user ON public.pattern_suggestion_log USING btree (user_id, suggested_at DESC);


--
-- Name: idx_presence_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_presence_log_created ON public.presence_log USING btree (created_at DESC);


--
-- Name: idx_presence_log_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_presence_log_user_time ON public.presence_log USING btree (user_id, created_at DESC);


--
-- Name: idx_progress_photo_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_progress_photo_user_created ON public.progress_photo USING btree (user_id, created_at DESC);


--
-- Name: idx_project_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_project_entity ON public.project_entity_link USING btree (project_id, relevance_score DESC);


--
-- Name: idx_project_tags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_project_tags ON public.project USING gin (tags);


--
-- Name: idx_project_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_project_user_status ON public.project USING btree (user_id, status);


--
-- Name: idx_prompt_proposals_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prompt_proposals_agent ON public.prompt_proposals USING btree (target_agent, created_at DESC);


--
-- Name: idx_prompt_proposals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prompt_proposals_status ON public.prompt_proposals USING btree (status);


--
-- Name: idx_prompt_versions_agent_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prompt_versions_agent_section ON public.prompt_versions USING btree (agent, section, created_at DESC);


--
-- Name: idx_raw_buffer_stats_stream_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_raw_buffer_stats_stream_time ON public.raw_buffer_stats USING btree (stream_type, window_start DESC);


--
-- Name: idx_recipe_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recipe_category ON public.recipe USING btree (user_id, category);


--
-- Name: idx_recipe_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recipe_user ON public.recipe USING btree (user_id);


--
-- Name: idx_recovery_log_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recovery_log_user_date ON public.daily_recovery_log USING btree (user_id, log_date DESC);


--
-- Name: idx_reflection_hypotheses_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_hypotheses_status ON public.reflection_hypotheses USING btree (status, test_deadline);


--
-- Name: idx_reflection_obs_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_obs_agent ON public.reflection_observations USING btree (subject_agent, created_at DESC);


--
-- Name: idx_reflection_obs_pattern; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_obs_pattern ON public.reflection_observations USING btree (pattern_id) WHERE (pattern_id IS NOT NULL);


--
-- Name: idx_reflection_obs_type_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_obs_type_time ON public.reflection_observations USING btree (observation_type, created_at DESC);


--
-- Name: idx_reflection_patterns_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_patterns_status ON public.reflection_patterns USING btree (status);


--
-- Name: idx_reflection_patterns_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reflection_patterns_type ON public.reflection_patterns USING btree (pattern_type, confidence DESC);


--
-- Name: idx_research_message_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_message_plan_id ON public.research_message USING btree (plan_id);


--
-- Name: idx_research_message_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_message_status ON public.research_message USING btree (status);


--
-- Name: idx_research_plan_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_plan_status ON public.research_plan USING btree (status);


--
-- Name: idx_research_plan_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_plan_user_id ON public.research_plan USING btree (user_id);


--
-- Name: idx_sara_commitment_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_commitment_user_status ON public.sara_commitment USING btree (user_id, status);


--
-- Name: idx_sara_goal_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_goal_status ON public.sara_goal USING btree (status, last_progress_at DESC);


--
-- Name: idx_sara_journal_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_journal_conversation ON public.sara_journal USING btree (conversation_id);


--
-- Name: idx_sara_journal_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_journal_type ON public.sara_journal USING btree (entry_type);


--
-- Name: idx_sara_journal_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_journal_user_created ON public.sara_journal USING btree (user_id, created_at);


--
-- Name: idx_sara_reflection_lesson_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_reflection_lesson_lookup ON public.sara_reflection USING btree (reflection_type, is_active) WHERE (((reflection_type)::text = 'mistake'::text) AND (is_active = true));


--
-- Name: idx_sara_soul_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sara_soul_section ON public.sara_soul USING btree (section);


--
-- Name: idx_say_candidate_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_say_candidate_user_status ON public.say_candidate USING btree (user_id, status);


--
-- Name: idx_say_candidate_valid_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_say_candidate_valid_until ON public.say_candidate USING btree (valid_until) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_scheduled_job_singular_class; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_job_singular_class ON public.scheduled_job USING btree (singular_class);


--
-- Name: idx_shadow_event_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_event_session ON public.shadow_event USING btree (session_id);


--
-- Name: idx_shadow_event_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_event_timestamp ON public.shadow_event USING btree ("timestamp" DESC);


--
-- Name: idx_shadow_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_event_type ON public.shadow_event USING btree (event_type);


--
-- Name: idx_shadow_note_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_note_session ON public.shadow_note USING btree (session_id);


--
-- Name: idx_shadow_note_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_note_type ON public.shadow_note USING btree (note_type);


--
-- Name: idx_shadow_session_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_session_started ON public.shadow_session USING btree (started_at DESC);


--
-- Name: idx_shadow_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_session_status ON public.shadow_session USING btree (status);


--
-- Name: idx_shadow_session_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_session_user ON public.shadow_session USING btree (user_id);


--
-- Name: idx_shadow_summary_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_summary_session ON public.shadow_summary USING btree (session_id);


--
-- Name: idx_shared_content_shared_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shared_content_shared_at ON public.shared_content USING btree (shared_at DESC);


--
-- Name: idx_shared_content_user_consolidated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shared_content_user_consolidated ON public.shared_content USING btree (user_id, consolidated) WHERE ((status)::text = 'kept'::text);


--
-- Name: idx_shared_content_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shared_content_user_status ON public.shared_content USING btree (user_id, status);


--
-- Name: idx_singular_context_turn_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_singular_context_turn_log_created ON public.singular_context_turn_log USING btree (created_at DESC);


--
-- Name: idx_soul_proposals_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_soul_proposals_section ON public.soul_change_proposals USING btree (section);


--
-- Name: idx_soul_proposals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_soul_proposals_status ON public.soul_change_proposals USING btree (status);


--
-- Name: idx_standing_order_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_standing_order_user_status ON public.standing_order USING btree (user_id, status);


--
-- Name: idx_tabata_preset_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tabata_preset_user ON public.tabata_preset USING btree (user_id, sort_order);


--
-- Name: idx_tangent_queue_user_topic_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tangent_queue_user_topic_status ON public.tangent_queue USING btree (user_id, parent_topic_id, status);


--
-- Name: idx_tasks_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_created_at ON public.jarvis_tasks USING btree (created_at);


--
-- Name: idx_tasks_user_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_user_state ON public.jarvis_tasks USING btree (user_id, state);


--
-- Name: idx_thread_archived; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_archived ON public.conversation_thread USING btree (user_id, archived);


--
-- Name: idx_thread_tags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_tags ON public.conversation_thread USING gin (tags);


--
-- Name: idx_thread_user_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_user_activity ON public.conversation_thread USING btree (user_id, last_activity DESC);


--
-- Name: idx_user_activity_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_activity_log_user_id ON public.user_activity_log USING btree (user_id);


--
-- Name: idx_workout_log_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_log_session ON public.workout_log USING btree (session_date, user_id);


--
-- Name: idx_workout_log_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_log_template ON public.workout_log USING btree (template_id);


--
-- Name: idx_workout_session_active_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_session_active_session ON public.workout_session USING btree (active_session_id) WHERE (active_session_id IS NOT NULL);


--
-- Name: idx_workout_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_session_status ON public.workout_session USING btree (user_id, status);


--
-- Name: idx_workout_session_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_session_template ON public.workout_session USING btree (template_id);


--
-- Name: idx_workout_session_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workout_session_user_date ON public.workout_session USING btree (user_id, session_date DESC);


--
-- Name: idx_workspace_states_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workspace_states_user_id ON public.workspace_states USING btree (user_id);


--
-- Name: idx_world_brief_patch_log_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_world_brief_patch_log_section ON public.world_brief_patch_log USING btree (user_id, section);


--
-- Name: idx_world_brief_patch_log_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_world_brief_patch_log_user_created ON public.world_brief_patch_log USING btree (user_id, created_at);


--
-- Name: ix_action_why_trace_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_why_trace_user_id ON public.action_why_trace USING btree (user_id);


--
-- Name: ix_active_workout_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_active_workout_session_status ON public.active_workout_session USING btree (status);


--
-- Name: ix_active_workout_session_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_active_workout_session_user_active ON public.active_workout_session USING btree (user_id) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_active_workout_session_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_active_workout_session_user_id ON public.active_workout_session USING btree (user_id);


--
-- Name: ix_app_user_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_app_user_email ON public.app_user USING btree (email);


--
-- Name: ix_artifacts_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_created_at ON public.artifacts USING btree (created_at);


--
-- Name: ix_artifacts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_type ON public.artifacts USING btree (artifact_type);


--
-- Name: ix_artifacts_user_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_user_conversation ON public.artifacts USING btree (user_id, conversation_id);


--
-- Name: ix_artifacts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_user_id ON public.artifacts USING btree (user_id);


--
-- Name: ix_attention_policy_snapshot_cell; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attention_policy_snapshot_cell ON public.attention_policy_snapshot USING btree (user_id, domain, context, captured_at DESC);


--
-- Name: ix_attention_policy_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attention_policy_user ON public.attention_policy USING btree (user_id);


--
-- Name: ix_aws_healthkit_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aws_healthkit_uuid ON public.active_workout_session USING btree (user_id, healthkit_workout_uuid) WHERE (healthkit_workout_uuid IS NOT NULL);


--
-- Name: ix_aws_start_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_aws_start_attempt ON public.active_workout_session USING btree (user_id, start_attempt_id) WHERE (start_attempt_id IS NOT NULL);


--
-- Name: ix_background_task_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_background_task_created_at ON public.background_task USING btree (created_at);


--
-- Name: ix_background_task_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_background_task_status ON public.background_task USING btree (status);


--
-- Name: ix_background_task_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_background_task_user_id ON public.background_task USING btree (user_id);


--
-- Name: ix_background_task_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_background_task_user_status ON public.background_task USING btree (user_id, status);


--
-- Name: ix_behavioral_pattern_ladder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_behavioral_pattern_ladder ON public.behavioral_pattern USING btree (ladder_status);


--
-- Name: ix_briefing_settings_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_briefing_settings_user_id ON public.briefing_settings USING btree (user_id);


--
-- Name: ix_calendar_event_ios_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_calendar_event_ios_unique ON public.calendar_event USING btree (user_id, ios_event_id, start_time) WHERE (ios_event_id IS NOT NULL);


--
-- Name: ix_calendar_event_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_calendar_event_owner ON public.calendar_event USING btree (owner);


--
-- Name: ix_calendar_event_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_calendar_event_source ON public.calendar_event USING btree (source);


--
-- Name: ix_cardio_log_session_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cardio_log_session_date ON public.cardio_log USING btree (session_date);


--
-- Name: ix_cardio_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cardio_log_user_id ON public.cardio_log USING btree (user_id);


--
-- Name: ix_chat_turn_trace_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_turn_trace_conversation ON public.chat_turn_trace USING btree (conversation_id, started_at DESC);


--
-- Name: ix_chat_turn_trace_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_turn_trace_started ON public.chat_turn_trace USING btree (started_at DESC);


--
-- Name: ix_chess_coaching_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chess_coaching_user_id ON public.chess_coaching_progress USING btree (user_id);


--
-- Name: ix_chess_game_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chess_game_started_at ON public.chess_game USING btree (started_at);


--
-- Name: ix_chess_game_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chess_game_status ON public.chess_game USING btree (status);


--
-- Name: ix_chess_game_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chess_game_user_id ON public.chess_game USING btree (user_id);


--
-- Name: ix_chess_stats_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chess_stats_user_id ON public.chess_stats USING btree (user_id);


--
-- Name: ix_code_session_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_code_session_conversation_id ON public.code_session USING btree (conversation_id);


--
-- Name: ix_code_session_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_code_session_user_id ON public.code_session USING btree (user_id);


--
-- Name: ix_context_snapshots_snapshot_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_snapshot_date ON public.context_snapshots USING btree (snapshot_date);


--
-- Name: ix_context_snapshots_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_context_snapshots_user_date ON public.context_snapshots USING btree (user_id, snapshot_date);


--
-- Name: ix_context_snapshots_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_user_id ON public.context_snapshots USING btree (user_id);


--
-- Name: ix_conversation_turn_client_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_conversation_turn_client_message_id ON public.conversation_turn USING btree (conversation_id, role, client_message_id) WHERE (client_message_id IS NOT NULL);


--
-- Name: ix_correction_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correction_user_active ON public.correction USING btree (user_id, active);


--
-- Name: ix_correction_user_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correction_user_subject ON public.correction USING btree (user_id, subject);


--
-- Name: ix_correlation_pattern_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_category ON public.correlation_pattern USING btree (pattern_category);


--
-- Name: ix_correlation_pattern_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_confidence ON public.correlation_pattern USING btree (confidence);


--
-- Name: ix_correlation_pattern_domains; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_domains ON public.correlation_pattern USING gin (source_domains);


--
-- Name: ix_correlation_pattern_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_embedding ON public.correlation_pattern USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='100');


--
-- Name: ix_correlation_pattern_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_user_id ON public.correlation_pattern USING btree (user_id);


--
-- Name: ix_correlation_pattern_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correlation_pattern_user_status ON public.correlation_pattern USING btree (user_id, status);


--
-- Name: ix_daily_rhythm_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_daily_rhythm_user_id ON public.daily_rhythm USING btree (user_id);


--
-- Name: ix_daily_task_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_daily_task_user_date ON public.daily_task USING btree (user_id, task_date);


--
-- Name: ix_desktop_focus_span_user_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_desktop_focus_span_user_start ON public.desktop_focus_span USING btree (user_id, start_ts);


--
-- Name: ix_dev_project_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dev_project_prefix ON public.dev_project USING btree (user_id, prefix);


--
-- Name: ix_dev_project_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dev_project_user ON public.dev_project USING btree (user_id);


--
-- Name: ix_device_registration_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_device_registration_token ON public.device_registration USING btree (device_token);


--
-- Name: ix_device_registration_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_device_registration_user ON public.device_registration USING btree (user_id);


--
-- Name: ix_directive_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_directive_user_active ON public.directive USING btree (user_id, active);


--
-- Name: ix_episode_client_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_episode_client_message_id ON public.episode USING btree (conversation_id, role, client_message_id) WHERE (client_message_id IS NOT NULL);


--
-- Name: ix_episode_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_embedding_hnsw ON public.episode USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: ix_episode_emotion_sentiment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_emotion_sentiment ON public.episode USING btree (((emotion_metadata ->> 'sentiment'::text))) WHERE (emotion_metadata IS NOT NULL);


--
-- Name: ix_episode_emotion_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_emotion_type ON public.episode USING btree (((emotion_metadata ->> 'primary_emotion'::text))) WHERE (emotion_metadata IS NOT NULL);


--
-- Name: ix_episode_importance; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_importance ON public.episode USING btree (importance);


--
-- Name: ix_episode_importance_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_importance_updated ON public.episode USING btree (importance_last_updated);


--
-- Name: ix_episode_reply_to_client_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_reply_to_client_message_id ON public.episode USING btree (reply_to_client_message_id) WHERE (reply_to_client_message_id IS NOT NULL);


--
-- Name: ix_episode_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_episode_user_created ON public.episode USING btree (user_id, created_at DESC);


--
-- Name: ix_event_log_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_event_log_event_id ON public.event_log USING btree (event_id);


--
-- Name: ix_event_log_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_log_event_type ON public.event_log USING btree (event_type);


--
-- Name: ix_event_log_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_log_timestamp ON public.event_log USING btree ("timestamp");


--
-- Name: ix_event_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_log_user_id ON public.event_log USING btree (user_id);


--
-- Name: ix_event_log_user_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_log_user_type ON public.event_log USING btree (user_id, event_type);


--
-- Name: ix_event_outbox_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_outbox_event_type ON public.event_outbox USING btree (event_type);


--
-- Name: ix_event_outbox_poll; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_outbox_poll ON public.event_outbox USING btree (status, next_retry_at, created_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: ix_event_outbox_retry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_outbox_retry ON public.event_outbox USING btree (next_retry_at) WHERE (((status)::text = 'pending'::text) AND (retry_count > 0));


--
-- Name: ix_event_outbox_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_outbox_status_created ON public.event_outbox USING btree (status, created_at) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying])::text[]));


--
-- Name: ix_exercise_library_movement_pattern; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exercise_library_movement_pattern ON public.exercise_library USING btree (movement_pattern);


--
-- Name: ix_exercise_pr_achieved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exercise_pr_achieved ON public.exercise_pr USING btree (achieved_at);


--
-- Name: ix_exercise_pr_user_exercise; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exercise_pr_user_exercise ON public.exercise_pr USING btree (user_id, exercise_name);


--
-- Name: ix_external_workout_dedup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_external_workout_dedup ON public.external_workout USING btree (user_id, source, external_id);


--
-- Name: ix_external_workout_sara_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_workout_sara_session ON public.external_workout USING btree (user_id, sara_session_id);


--
-- Name: ix_external_workout_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_workout_user_id ON public.external_workout USING btree (user_id);


--
-- Name: ix_external_workout_user_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_workout_user_started ON public.external_workout USING btree (user_id, started_at);


--
-- Name: ix_fatsecret_food_cache_barcode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fatsecret_food_cache_barcode ON public.fatsecret_food_cache USING btree (barcode);


--
-- Name: ix_fatsecret_food_cache_fatsecret_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fatsecret_food_cache_fatsecret_id ON public.fatsecret_food_cache USING btree (fatsecret_id);


--
-- Name: ix_fatsecret_food_cache_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fatsecret_food_cache_name ON public.fatsecret_food_cache USING btree (name);


--
-- Name: ix_fitness_idempotency_client_txn_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fitness_idempotency_client_txn_id ON public.fitness_idempotency USING btree (client_txn_id);


--
-- Name: ix_fitness_note_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fitness_note_user_id ON public.fitness_note USING btree (user_id);


--
-- Name: ix_fitness_program_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fitness_program_user_active ON public.fitness_program USING btree (user_id, is_active);


--
-- Name: ix_food_log_item_food_log; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_food_log_item_food_log ON public.food_log_item USING btree (food_log_id);


--
-- Name: ix_food_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_food_log_user_id ON public.food_log USING btree (user_id);


--
-- Name: ix_food_log_user_logged_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_food_log_user_logged_at ON public.food_log USING btree (user_id, logged_at DESC);


--
-- Name: ix_git_branch_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_git_branch_name ON public.git_branch USING btree (project_id, name);


--
-- Name: ix_git_branch_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_branch_project ON public.git_branch USING btree (project_id);


--
-- Name: ix_git_commit_branch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_commit_branch ON public.git_commit USING btree (project_id, branch);


--
-- Name: ix_git_commit_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_commit_date ON public.git_commit USING btree (project_id, committed_at);


--
-- Name: ix_git_commit_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_commit_project ON public.git_commit USING btree (project_id);


--
-- Name: ix_git_commit_sha; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_git_commit_sha ON public.git_commit USING btree (project_id, sha);


--
-- Name: ix_goal_progress_goal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_progress_goal_id ON public.goal_progress USING btree (goal_id);


--
-- Name: ix_goal_progress_logged_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_progress_logged_at ON public.goal_progress USING btree (logged_at);


--
-- Name: ix_goal_progress_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_progress_source ON public.goal_progress USING btree (source, source_id);


--
-- Name: ix_goal_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_status ON public.goal USING btree (status);


--
-- Name: ix_goal_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_type ON public.goal USING btree (goal_type);


--
-- Name: ix_goal_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_user_id ON public.goal USING btree (user_id);


--
-- Name: ix_goal_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_goal_user_status ON public.goal USING btree (user_id, status);


--
-- Name: ix_health_alert_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_alert_user ON public.health_alert USING btree (user_id);


--
-- Name: ix_health_alert_user_type_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_alert_user_type_recent ON public.health_alert USING btree (user_id, alert_type, created_at);


--
-- Name: ix_health_baseline_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_health_baseline_unique ON public.health_baseline USING btree (user_id, metric_type, period_type);


--
-- Name: ix_health_baseline_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_baseline_user ON public.health_baseline USING btree (user_id);


--
-- Name: ix_health_insight_triggered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_insight_triggered ON public.health_insight USING btree (triggered_at);


--
-- Name: ix_health_insight_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_insight_type ON public.health_insight USING btree (insight_type);


--
-- Name: ix_health_insight_user_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_insight_user_severity ON public.health_insight USING btree (user_id, severity);


--
-- Name: ix_health_insight_user_surfaced; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_insight_user_surfaced ON public.health_insight USING btree (user_id, surfaced_count);


--
-- Name: ix_health_metric_dedup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_health_metric_dedup ON public.health_metric USING btree (user_id, metric_type, recorded_at);


--
-- Name: ix_health_metric_user_recorded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_metric_user_recorded ON public.health_metric USING btree (user_id, recorded_at);


--
-- Name: ix_health_metric_user_type_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_metric_user_type_time ON public.health_metric USING btree (user_id, metric_type, recorded_at);


--
-- Name: ix_health_weekly_report_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_health_weekly_report_user_id ON public.health_weekly_report USING btree (user_id);


--
-- Name: ix_held_notification_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_held_notification_pending ON public.held_notification USING btree (user_id, status);


--
-- Name: ix_held_notification_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_held_notification_user_id ON public.held_notification USING btree (user_id);


--
-- Name: ix_host_alert_host_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_alert_host_id ON public.host_alert USING btree (host_id);


--
-- Name: ix_host_alert_rule; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_alert_rule ON public.host_alert USING btree (rule);


--
-- Name: ix_host_diag_command_host_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_diag_command_host_id ON public.host_diag_command USING btree (host_id);


--
-- Name: ix_host_diag_command_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_diag_command_status ON public.host_diag_command USING btree (status);


--
-- Name: ix_host_metric_host_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_metric_host_id ON public.host_metric USING btree (host_id);


--
-- Name: ix_host_metric_host_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_host_metric_host_ts ON public.host_metric USING btree (host_id, ts);


--
-- Name: ix_hwr_week_end; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hwr_week_end ON public.health_weekly_report USING btree (week_end);


--
-- Name: ix_hypothesis_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hypothesis_confidence ON public.hypothesis USING btree (confidence);


--
-- Name: ix_hypothesis_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hypothesis_domain ON public.hypothesis USING btree (domain);


--
-- Name: ix_hypothesis_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hypothesis_embedding ON public.hypothesis USING hnsw (embedding public.vector_l2_ops);


--
-- Name: ix_hypothesis_last_evidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hypothesis_last_evidence ON public.hypothesis USING btree (last_evidence_at);


--
-- Name: ix_hypothesis_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hypothesis_status ON public.hypothesis USING btree (status);


--
-- Name: ix_intelligence_item_discovered_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_item_discovered_at ON public.intelligence_item USING btree (discovered_at);


--
-- Name: ix_intelligence_item_dismissed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_item_dismissed ON public.intelligence_item USING btree (dismissed);


--
-- Name: ix_intelligence_item_novelty_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_item_novelty_score ON public.intelligence_item USING btree (novelty_score);


--
-- Name: ix_intelligence_item_relevance_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_item_relevance_score ON public.intelligence_item USING btree (relevance_score);


--
-- Name: ix_intelligence_item_source_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_item_source_category ON public.intelligence_item USING btree (source_category);


--
-- Name: ix_intelligence_report_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_report_created_at ON public.intelligence_report USING btree (created_at);


--
-- Name: ix_intelligence_report_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_report_period ON public.intelligence_report USING btree (period_start, period_end);


--
-- Name: ix_intelligence_report_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_report_type ON public.intelligence_report USING btree (report_type);


--
-- Name: ix_intelligence_report_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_report_user_id ON public.intelligence_report USING btree (user_id);


--
-- Name: ix_intelligence_report_user_type_period; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_intelligence_report_user_type_period ON public.intelligence_report USING btree (user_id, report_type, period_start);


--
-- Name: ix_known_place_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_known_place_status ON public.known_place USING btree (status);


--
-- Name: ix_known_place_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_known_place_user_id ON public.known_place USING btree (user_id);


--
-- Name: ix_learning_artifact_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_artifact_topic ON public.learning_artifact USING btree (topic_id);


--
-- Name: ix_learning_artifact_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_artifact_type ON public.learning_artifact USING btree (artifact_type);


--
-- Name: ix_learning_artifact_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_artifact_user ON public.learning_artifact USING btree (user_id);


--
-- Name: ix_learning_blueprint_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_blueprint_status ON public.learning_blueprint USING btree (status);


--
-- Name: ix_learning_blueprint_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_blueprint_user ON public.learning_blueprint USING btree (user_id);


--
-- Name: ix_learning_guide_job_blueprint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_guide_job_blueprint ON public.learning_guide_job USING btree (blueprint_id);


--
-- Name: ix_learning_guide_job_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_guide_job_created_at ON public.learning_guide_job USING btree (created_at);


--
-- Name: ix_learning_guide_job_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_guide_job_status ON public.learning_guide_job USING btree (status);


--
-- Name: ix_learning_guide_job_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_guide_job_user ON public.learning_guide_job USING btree (user_id);


--
-- Name: ix_learning_progress_next_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_progress_next_review ON public.learning_progress USING btree (next_review_at);


--
-- Name: ix_learning_progress_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_progress_topic ON public.learning_progress USING btree (topic_id);


--
-- Name: ix_learning_progress_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_progress_user ON public.learning_progress USING btree (user_id);


--
-- Name: ix_learning_session_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_session_started ON public.learning_session USING btree (started_at);


--
-- Name: ix_learning_session_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_session_topic ON public.learning_session USING btree (topic_id);


--
-- Name: ix_learning_session_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_session_user ON public.learning_session USING btree (user_id);


--
-- Name: ix_learning_topic_blueprint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_topic_blueprint ON public.learning_topic USING btree (blueprint_id);


--
-- Name: ix_learning_topic_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_topic_parent ON public.learning_topic USING btree (parent_id);


--
-- Name: ix_learning_topic_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_topic_status ON public.learning_topic USING btree (status);


--
-- Name: ix_learning_topic_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learning_topic_user ON public.learning_topic USING btree (user_id);


--
-- Name: ix_life_fact_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_life_fact_user ON public.life_fact USING btree (user_id);


--
-- Name: ix_live_activity_logical; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_live_activity_logical ON public.live_activity_registration USING btree (user_id, logical_id, is_active);


--
-- Name: ix_live_activity_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_live_activity_user_active ON public.live_activity_registration USING btree (user_id, is_active, kind);


--
-- Name: ix_location_event_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_location_event_user_created ON public.location_event USING btree (user_id, created_at);


--
-- Name: ix_location_trigger_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_location_trigger_status ON public.location_trigger USING btree (status);


--
-- Name: ix_location_trigger_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_location_trigger_user_id ON public.location_trigger USING btree (user_id);


--
-- Name: ix_machine_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_machine_device_id ON public.machine USING btree (device_id);


--
-- Name: ix_machine_last_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_machine_last_activity ON public.machine USING btree (user_id, last_activity_at);


--
-- Name: ix_machine_online; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_machine_online ON public.machine USING btree (user_id, is_online);


--
-- Name: ix_machine_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_machine_user_id ON public.machine USING btree (user_id);


--
-- Name: ix_managed_host_machine_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_managed_host_machine_id ON public.managed_host USING btree (machine_id);


--
-- Name: ix_managed_host_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_managed_host_name ON public.managed_host USING btree (name);


--
-- Name: ix_managed_host_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_managed_host_user_id ON public.managed_host USING btree (user_id);


--
-- Name: ix_mem_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mem_embedding_hnsw ON public.memory_embedding USING hnsw (embedding public.vector_l2_ops);


--
-- Name: ix_memory_embedding_trace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_embedding_trace ON public.memory_embedding USING btree (trace_id, head);


--
-- Name: ix_memory_trace_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_trace_created_at ON public.memory_trace USING btree (created_at);


--
-- Name: ix_memory_trace_salience; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_trace_salience ON public.memory_trace USING btree (salience);


--
-- Name: ix_memory_trace_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_trace_user_id ON public.memory_trace USING btree (user_id);


--
-- Name: ix_ml_feature_daily_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ml_feature_daily_user_date ON public.ml_feature_daily USING btree (user_id, feature_date);


--
-- Name: ix_ml_model_version_family_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ml_model_version_family_status ON public.ml_model_version USING btree (family, status);


--
-- Name: ix_ml_notification_outcome_user_sent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ml_notification_outcome_user_sent ON public.ml_notification_outcome USING btree (user_id, sent_at);


--
-- Name: ix_ml_prediction_log_family_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ml_prediction_log_family_created ON public.ml_prediction_log USING btree (model_family, created_at);


--
-- Name: ix_morning_brief_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_morning_brief_user_created ON public.morning_brief USING btree (user_id, created_at);


--
-- Name: ix_morning_brief_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_morning_brief_user_date ON public.morning_brief USING btree (user_id, brief_date);


--
-- Name: ix_note_connection_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_connection_user ON public.note_connection USING btree (user_id);


--
-- Name: ix_note_user_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_user_folder ON public.note USING btree (user_id, folder_id);


--
-- Name: ix_note_user_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_user_updated ON public.note USING btree (user_id, updated_at DESC);


--
-- Name: ix_notification_log_feedback; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_log_feedback ON public.notification_log USING btree (user_id, category, sent_at) WHERE (sent = true);


--
-- Name: ix_notification_preference_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_preference_user_id ON public.notification_preference USING btree (user_id);


--
-- Name: ix_pattern_discovery_log_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pattern_discovery_log_user_date ON public.pattern_discovery_log USING btree (user_id, started_at);


--
-- Name: ix_pattern_discovery_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pattern_discovery_log_user_id ON public.pattern_discovery_log USING btree (user_id);


--
-- Name: ix_person_emails; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_person_emails ON public.person USING gin (emails);


--
-- Name: ix_person_last_interaction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_person_last_interaction ON public.person USING btree (user_id, last_interaction_at DESC);


--
-- Name: ix_person_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_person_user_id ON public.person USING btree (user_id);


--
-- Name: ix_pkg_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pkg_embedding_hnsw ON public.pkg_embedding USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: ix_pkg_embedding_node_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pkg_embedding_node_type ON public.pkg_embedding USING btree (node_type);


--
-- Name: ix_prediction_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prediction_confidence ON public.prediction USING btree (confidence);


--
-- Name: ix_prediction_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prediction_domain ON public.prediction USING btree (domain);


--
-- Name: ix_prediction_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prediction_key ON public.prediction USING btree (prediction_key);


--
-- Name: ix_prediction_outcome; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prediction_outcome ON public.prediction USING btree (outcome);


--
-- Name: ix_prediction_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prediction_pending ON public.prediction USING btree (outcome, window_end);


--
-- Name: ix_project_file_project_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_file_project_folder ON public.project_file USING btree (project_id, folder_id);


--
-- Name: ix_project_file_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_project_file_storage_key ON public.project_file USING btree (storage_key);


--
-- Name: ix_project_file_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_file_user ON public.project_file USING btree (user_id);


--
-- Name: ix_project_folder_project_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_folder_project_parent ON public.project_folder USING btree (project_id, parent_id);


--
-- Name: ix_project_folder_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_folder_user ON public.project_folder USING btree (user_id);


--
-- Name: ix_promotion_event_domain_context; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_promotion_event_domain_context ON public.promotion_event USING btree (user_id, domain, context);


--
-- Name: ix_promotion_event_notif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_promotion_event_notif ON public.promotion_event USING btree (notification_id);


--
-- Name: ix_promotion_event_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_promotion_event_user_created ON public.promotion_event USING btree (user_id, created_at DESC);


--
-- Name: ix_proxmox_container_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proxmox_container_session ON public.proxmox_container USING btree (session_id);


--
-- Name: ix_proxmox_container_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proxmox_container_status ON public.proxmox_container USING btree (status);


--
-- Name: ix_proxmox_container_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proxmox_container_user ON public.proxmox_container USING btree (user_id);


--
-- Name: ix_proxmox_container_vmid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proxmox_container_vmid ON public.proxmox_container USING btree (vmid);


--
-- Name: ix_pull_request_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_pull_request_number ON public.pull_request USING btree (project_id, pr_number);


--
-- Name: ix_pull_request_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pull_request_project ON public.pull_request USING btree (project_id);


--
-- Name: ix_pull_request_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pull_request_status ON public.pull_request USING btree (project_id, status);


--
-- Name: ix_qa_checklist_item_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_checklist_item_project ON public.qa_checklist_item USING btree (project_id, is_active, sort_order);


--
-- Name: ix_qa_commit_result_commit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_commit_result_commit ON public.qa_commit_result USING btree (commit_id);


--
-- Name: ix_qa_commit_result_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qa_commit_result_project_status ON public.qa_commit_result USING btree (project_id, status);


--
-- Name: ix_reasoning_trace_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reasoning_trace_conversation ON public.reasoning_trace USING btree (conversation_id);


--
-- Name: ix_reasoning_trace_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reasoning_trace_created ON public.reasoning_trace USING btree (created_at);


--
-- Name: ix_reasoning_trace_episode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reasoning_trace_episode ON public.reasoning_trace USING btree (episode_id);


--
-- Name: ix_recipe_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recipe_embedding_hnsw ON public.recipe USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: ix_recipe_meal_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recipe_meal_type ON public.recipe USING btree (user_id, meal_type);


--
-- Name: ix_recipe_starred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recipe_starred ON public.recipe USING btree (user_id, starred) WHERE starred;


--
-- Name: ix_recipe_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recipe_updated_at ON public.recipe USING btree (updated_at DESC);


--
-- Name: ix_reminder_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reminder_event_id ON public.reminder USING btree (event_id);


--
-- Name: ix_research_brief_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_brief_user_date ON public.research_brief USING btree (user_id, brief_date);


--
-- Name: ix_research_job_report; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_job_report ON public.research_job USING btree (report_id);


--
-- Name: ix_research_job_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_job_status ON public.research_job USING btree (status);


--
-- Name: ix_research_job_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_job_user ON public.research_job USING btree (user_id);


--
-- Name: ix_research_plan_origin_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_plan_origin_status ON public.research_plan USING btree (origin, status);


--
-- Name: ix_research_plan_user_live; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_plan_user_live ON public.research_plan USING btree (user_id, status) WHERE ((status)::text = ANY ((ARRAY['draft'::character varying, 'running'::character varying, 'stuck'::character varying, 'stalled'::character varying, 'paused'::character varying])::text[]));


--
-- Name: ix_research_report_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_report_status ON public.research_report USING btree (status);


--
-- Name: ix_research_report_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_report_topic ON public.research_report USING btree (topic_id);


--
-- Name: ix_research_report_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_report_user ON public.research_report USING btree (user_id);


--
-- Name: ix_sara_activity_audience; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_activity_audience ON public.sara_activity_log USING btree (audience);


--
-- Name: ix_sara_activity_dedup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_activity_dedup ON public.sara_activity_log USING btree (dedup_key);


--
-- Name: ix_sara_activity_log_created_at_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_activity_log_created_at_desc ON public.sara_activity_log USING btree (created_at DESC);


--
-- Name: ix_sara_activity_log_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_activity_log_embedding ON public.sara_activity_log USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: ix_sara_activity_log_kind_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_activity_log_kind_created_at ON public.sara_activity_log USING btree (kind, created_at DESC);


--
-- Name: ix_sara_inbox_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_inbox_active ON public.sara_inbox USING btree (created_at DESC) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'in_progress'::character varying])::text[]));


--
-- Name: ix_sara_interest_acted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_interest_acted ON public.sara_interest USING btree (last_acted_at NULLS FIRST);


--
-- Name: ix_sara_interest_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_interest_embedding ON public.sara_interest USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: ix_sara_interest_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_interest_status ON public.sara_interest USING btree (status);


--
-- Name: ix_sara_interest_weight; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_interest_weight ON public.sara_interest USING btree (weight DESC);


--
-- Name: ix_sara_reflection_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_reflection_active ON public.sara_reflection USING btree (is_active);


--
-- Name: ix_sara_reflection_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_reflection_confidence ON public.sara_reflection USING btree (confidence);


--
-- Name: ix_sara_reflection_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_reflection_domain ON public.sara_reflection USING btree (domain);


--
-- Name: ix_sara_reflection_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_reflection_embedding ON public.sara_reflection USING hnsw (embedding public.vector_l2_ops);


--
-- Name: ix_sara_reflection_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_reflection_type ON public.sara_reflection USING btree (reflection_type);


--
-- Name: ix_sara_tool_invocation_tool; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_tool_invocation_tool ON public.sara_tool_invocation USING btree (tool_id, started_at DESC);


--
-- Name: ix_sara_tool_version_tool; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sara_tool_version_tool ON public.sara_tool_version USING btree (tool_id, version DESC);


--
-- Name: ix_saved_meal_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_saved_meal_user_active ON public.saved_meal USING btree (user_id) WHERE (archived_at IS NULL);


--
-- Name: ix_scheduled_home_action_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_home_action_pending ON public.scheduled_home_action USING btree (status, scheduled_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: ix_scheduled_home_action_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_home_action_user ON public.scheduled_home_action USING btree (user_id, scheduled_at);


--
-- Name: ix_scheduled_job_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_job_category ON public.scheduled_job USING btree (category);


--
-- Name: ix_scheduled_job_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_job_enabled ON public.scheduled_job USING btree (enabled);


--
-- Name: ix_scratchpad_user_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scratchpad_user_active ON public.scratchpad_entry USING btree (user_id, cleared);


--
-- Name: ix_shadow_event_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_event_content_hash ON public.shadow_event USING btree (session_id, content_hash);


--
-- Name: ix_shadow_screenshot_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_screenshot_hash ON public.shadow_screenshot USING btree (session_id, image_hash);


--
-- Name: ix_shadow_screenshot_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_screenshot_session ON public.shadow_screenshot USING btree (session_id);


--
-- Name: ix_shadow_screenshot_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_screenshot_timestamp ON public.shadow_screenshot USING btree (session_id, "timestamp");


--
-- Name: ix_signal_baseline_user_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signal_baseline_user_domain ON public.signal_baseline USING btree (user_id, domain);


--
-- Name: ix_source_chunk_chapter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_chunk_chapter ON public.source_chunk USING btree (chapter_ref);


--
-- Name: ix_source_chunk_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_chunk_embedding ON public.source_chunk USING hnsw (embedding public.vector_l2_ops);


--
-- Name: ix_source_chunk_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_chunk_source ON public.source_chunk USING btree (source_id);


--
-- Name: ix_stimulus_habituation_generator; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stimulus_habituation_generator ON public.stimulus_habituation USING btree (generator, strength);


--
-- Name: ix_subconscious_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subconscious_log_created ON public.subconscious_log USING btree (created_at);


--
-- Name: ix_subconscious_log_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subconscious_log_user_time ON public.subconscious_log USING btree (user_id, snapshot_at);


--
-- Name: ix_subconscious_nudge_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subconscious_nudge_expires ON public.subconscious_nudge USING btree (expires_at);


--
-- Name: ix_subconscious_nudge_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subconscious_nudge_user_status ON public.subconscious_nudge USING btree (user_id, status);


--
-- Name: ix_subconscious_nudge_user_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subconscious_nudge_user_type ON public.subconscious_nudge USING btree (user_id, nudge_type, created_at);


--
-- Name: ix_subconscious_state_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_subconscious_state_user ON public.subconscious_state USING btree (user_id);


--
-- Name: ix_surface_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_surface_status ON public.surface USING btree (status);


--
-- Name: ix_surface_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_surface_user_id ON public.surface USING btree (user_id);


--
-- Name: ix_system_event_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_event_category ON public.system_event USING btree (category);


--
-- Name: ix_system_event_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_event_created_at ON public.system_event USING btree (created_at);


--
-- Name: ix_system_event_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_event_event_id ON public.system_event USING btree (event_id);


--
-- Name: ix_system_event_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_event_level ON public.system_event USING btree (level);


--
-- Name: ix_tabata_preset_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tabata_preset_user_id ON public.tabata_preset USING btree (user_id);


--
-- Name: ix_task_failure_last_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_failure_last_seen ON public.task_failure USING btree (last_seen);


--
-- Name: ix_task_failure_task_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_failure_task_name ON public.task_failure USING btree (task_name);


--
-- Name: ix_task_item_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_task_item_number ON public.task_item USING btree (project_id, task_number);


--
-- Name: ix_task_item_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_item_project ON public.task_item USING btree (project_id);


--
-- Name: ix_task_item_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_item_status ON public.task_item USING btree (project_id, status);


--
-- Name: ix_task_item_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_item_user ON public.task_item USING btree (user_id);


--
-- Name: ix_temerant_ledger_character_attr_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temerant_ledger_character_attr_time ON public.temerant_xp_ledger USING btree (character_id, attribute, occurred_at);


--
-- Name: ix_temerant_ledger_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temerant_ledger_source ON public.temerant_xp_ledger USING btree (source_type, source_ref_id);


--
-- Name: ix_temerant_ledger_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temerant_ledger_user_date ON public.temerant_xp_ledger USING btree (user_id, local_date);


--
-- Name: ix_temerant_rpg_scene_turn_scene_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temerant_rpg_scene_turn_scene_idx ON public.temerant_rpg_scene_turn USING btree (scene_id, turn_index);


--
-- Name: ix_temerant_rpg_scene_user_opened; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temerant_rpg_scene_user_opened ON public.temerant_rpg_scene USING btree (user_id, opened_at);


--
-- Name: ix_template_exercise_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_template_exercise_template ON public.template_exercise USING btree (template_id);


--
-- Name: ix_temporal_bin_date_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temporal_bin_date_type ON public.temporal_bin USING btree (bin_date, bin_type);


--
-- Name: ix_temporal_bin_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temporal_bin_user_date ON public.temporal_bin USING btree (user_id, bin_date);


--
-- Name: ix_temporal_bin_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_temporal_bin_user_id ON public.temporal_bin USING btree (user_id);


--
-- Name: ix_token_usage_aggregate_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_usage_aggregate_user_id ON public.token_usage_aggregate USING btree (user_id);


--
-- Name: ix_token_usage_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_usage_created_at ON public.token_usage USING btree (created_at);


--
-- Name: ix_token_usage_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_usage_session_id ON public.token_usage USING btree (session_id);


--
-- Name: ix_token_usage_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_usage_user_date ON public.token_usage USING btree (user_id, created_at);


--
-- Name: ix_token_usage_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_usage_user_id ON public.token_usage USING btree (user_id);


--
-- Name: ix_topic_connection_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_connection_source ON public.topic_connection USING btree (source_topic_id);


--
-- Name: ix_topic_connection_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_connection_target ON public.topic_connection USING btree (target_topic_id);


--
-- Name: ix_topic_connection_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_connection_user ON public.topic_connection USING btree (user_id);


--
-- Name: ix_topic_scratchpad_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_scratchpad_topic ON public.topic_scratchpad USING btree (topic_id);


--
-- Name: ix_topic_scratchpad_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_scratchpad_user ON public.topic_scratchpad USING btree (user_id);


--
-- Name: ix_topic_source_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_source_status ON public.topic_source USING btree (fetch_status);


--
-- Name: ix_topic_source_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_source_topic ON public.topic_source USING btree (topic_id);


--
-- Name: ix_topic_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_source_type ON public.topic_source USING btree (source_type);


--
-- Name: ix_topic_source_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_topic_source_user ON public.topic_source USING btree (user_id);


--
-- Name: ix_tunable_setting_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tunable_setting_category ON public.tunable_setting USING btree (category);


--
-- Name: ix_user_life_context_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_life_context_user_id ON public.user_life_context USING btree (user_id);


--
-- Name: ix_user_settings_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_settings_user_id ON public.user_settings USING btree (user_id);


--
-- Name: ix_voice_interaction_log_user_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_interaction_log_user_started ON public.voice_interaction_log USING btree (user_id, started_at);


--
-- Name: ix_wap_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wap_user_status ON public.workout_adjustment_proposal USING btree (user_id, status);


--
-- Name: ix_weight_trend_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_weight_trend_user_date ON public.weight_trend USING btree (user_id, date);


--
-- Name: ix_why_trace_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_why_trace_recent ON public.action_why_trace USING btree (user_id, created_at);


--
-- Name: ix_workout_adjustment_proposal_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_adjustment_proposal_session_id ON public.workout_adjustment_proposal USING btree (session_id);


--
-- Name: ix_workout_adjustment_proposal_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_adjustment_proposal_user_id ON public.workout_adjustment_proposal USING btree (user_id);


--
-- Name: ix_workout_log_active_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_log_active_session_id ON public.workout_log USING btree (active_session_id);


--
-- Name: ix_workout_log_command; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_workout_log_command ON public.workout_log USING btree (command_id) WHERE (command_id IS NOT NULL);


--
-- Name: ix_workout_log_exercise_library_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_log_exercise_library_id ON public.workout_log USING btree (exercise_library_id);


--
-- Name: ix_workout_log_session_live; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_log_session_live ON public.workout_log USING btree (active_session_id, exercise_id) WHERE (voided_at IS NULL);


--
-- Name: ix_workout_log_set_group; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_log_set_group ON public.workout_log USING btree (set_group_id, group_sequence) WHERE (set_group_id IS NOT NULL);


--
-- Name: ix_workout_log_user_exercise_live; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_log_user_exercise_live ON public.workout_log USING btree (user_id, exercise_id, session_date DESC) WHERE ((voided_at IS NULL) AND ((set_kind)::text = 'working'::text));


--
-- Name: ix_workout_session_command_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_session_command_session_id ON public.workout_session_command USING btree (session_id);


--
-- Name: ix_workout_session_command_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_session_command_user_id ON public.workout_session_command USING btree (user_id);


--
-- Name: ix_workout_session_event_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_session_event_session_id ON public.workout_session_event USING btree (session_id);


--
-- Name: ix_workout_session_event_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workout_session_event_user_id ON public.workout_session_event USING btree (user_id);


--
-- Name: ix_workspace_job_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_job_status ON public.workspace_job USING btree (status);


--
-- Name: ix_workspace_job_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_job_user_id ON public.workspace_job USING btree (user_id);


--
-- Name: ix_world_attention_user_status_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_attention_user_status_score ON public.world_attention_item USING btree (user_id, status, aggregate_score);


--
-- Name: ix_world_disposition_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_disposition_user_created ON public.world_event_disposition USING btree (user_id, created_at);


--
-- Name: ix_world_entity_user_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_entity_user_kind ON public.world_entity USING btree (user_id, kind);


--
-- Name: ix_world_event_aggregate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_aggregate ON public.world_event USING btree (aggregate_type, aggregate_id, aggregate_version);


--
-- Name: ix_world_event_causation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_causation ON public.world_event USING btree (causation_id);


--
-- Name: ix_world_event_correlation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_correlation ON public.world_event USING btree (correlation_id);


--
-- Name: ix_world_event_processing_ready; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_processing_ready ON public.world_event_processing USING btree (status, next_attempt_at, leased_until);


--
-- Name: ix_world_event_user_kind_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_user_kind_occurred ON public.world_event USING btree (user_id, kind, occurred_at);


--
-- Name: ix_world_event_user_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_event_user_sequence ON public.world_event USING btree (user_id, sequence);


--
-- Name: ix_world_fact_source_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_fact_source_event ON public.world_fact USING btree (source_event_id);


--
-- Name: ix_world_fact_subject_predicate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_fact_subject_predicate ON public.world_fact USING btree (subject_entity_id, predicate);


--
-- Name: ix_world_fact_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_fact_user_key ON public.world_fact USING btree (user_id, fact_key);


--
-- Name: ix_world_fact_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_fact_user_status ON public.world_fact USING btree (user_id, status);


--
-- Name: ix_world_thread_user_status_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_world_thread_user_status_review ON public.world_thread USING btree (user_id, status, next_review_at);


--
-- Name: ix_wsc_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wsc_session_created ON public.workout_session_command USING btree (session_id, created_at);


--
-- Name: ix_wse_session_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wse_session_version ON public.workout_session_event USING btree (session_id, after_version);


--
-- Name: uq_folder_user_name_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_folder_user_name_parent ON public.folder USING btree (user_id, name, COALESCE(parent_id, '__ROOT__'::character varying));


--
-- Name: uq_notification_preference_user_category; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_notification_preference_user_category ON public.notification_preference USING btree (user_id, category);


--
-- Name: uq_temporal_bin_user_date_hour_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_temporal_bin_user_date_hour_type ON public.temporal_bin USING btree (user_id, bin_date, bin_hour, bin_type);


--
-- Name: uq_truth_maintenance_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_truth_maintenance_user_date ON public.truth_maintenance_report USING btree (user_id, ran_for_date);


--
-- Name: achievement achievement_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.achievement
    ADD CONSTRAINT achievement_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: action_ledger action_ledger_standing_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_ledger
    ADD CONSTRAINT action_ledger_standing_order_id_fkey FOREIGN KEY (standing_order_id) REFERENCES public.standing_order(id);


--
-- Name: active_workout_session active_workout_session_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_workout_session
    ADD CONSTRAINT active_workout_session_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.fitness_template(id) ON DELETE SET NULL;


--
-- Name: active_workout_session active_workout_session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_workout_session
    ADD CONSTRAINT active_workout_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: anchor_point anchor_point_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anchor_point
    ADD CONSTRAINT anchor_point_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: anchor_point anchor_point_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anchor_point
    ADD CONSTRAINT anchor_point_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: app_user_role app_user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_role
    ADD CONSTRAINT app_user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: attention_item attention_item_outbound_intent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attention_item
    ADD CONSTRAINT attention_item_outbound_intent_id_fkey FOREIGN KEY (outbound_intent_id) REFERENCES public.outbound_intent(outbound_intent_id) ON DELETE CASCADE;


--
-- Name: automation_execution_log automation_execution_log_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_execution_log
    ADD CONSTRAINT automation_execution_log_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.automation_task(id) ON DELETE CASCADE;


--
-- Name: automation_state_store automation_state_store_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_state_store
    ADD CONSTRAINT automation_state_store_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.automation_task(id) ON DELETE CASCADE;


--
-- Name: automation_task automation_task_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_task
    ADD CONSTRAINT automation_task_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: autonomy_action_trace autonomy_action_trace_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_action_trace
    ADD CONSTRAINT autonomy_action_trace_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_run_log(id);


--
-- Name: autonomy_mission_step autonomy_mission_step_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.autonomy_mission_step
    ADD CONSTRAINT autonomy_mission_step_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.autonomy_mission(id) ON DELETE CASCADE;


--
-- Name: body_state_calibration body_state_calibration_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_state_calibration
    ADD CONSTRAINT body_state_calibration_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: body_state_coefficients body_state_coefficients_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_state_coefficients
    ADD CONSTRAINT body_state_coefficients_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: candidate_skill candidate_skill_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_skill
    ADD CONSTRAINT candidate_skill_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: chess_coaching_progress chess_coaching_progress_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_coaching_progress
    ADD CONSTRAINT chess_coaching_progress_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: chess_game chess_game_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_game
    ADD CONSTRAINT chess_game_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: chess_stats chess_stats_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chess_stats
    ADD CONSTRAINT chess_stats_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: code_session code_session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.code_session
    ADD CONSTRAINT code_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: composed_utterance composed_utterance_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.composed_utterance
    ADD CONSTRAINT composed_utterance_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.say_candidate(id) ON DELETE CASCADE;


--
-- Name: consolidation_discards consolidation_discards_consolidation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consolidation_discards
    ADD CONSTRAINT consolidation_discards_consolidation_run_id_fkey FOREIGN KEY (consolidation_run_id) REFERENCES public.consolidation_runs(id) ON DELETE CASCADE;


--
-- Name: conversation_thread conversation_thread_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_thread
    ADD CONSTRAINT conversation_thread_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: daily_briefs daily_briefs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_briefs
    ADD CONSTRAINT daily_briefs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: daily_reflections daily_reflections_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_reflections
    ADD CONSTRAINT daily_reflections_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: daily_rhythm daily_rhythm_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_rhythm
    ADD CONSTRAINT daily_rhythm_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: daily_task daily_task_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_task
    ADD CONSTRAINT daily_task_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: desktop_focus_span desktop_focus_span_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desktop_focus_span
    ADD CONSTRAINT desktop_focus_span_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: doc_chunk doc_chunk_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_chunk
    ADD CONSTRAINT doc_chunk_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.document(id) ON DELETE CASCADE;


--
-- Name: email_attachment email_attachment_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_attachment
    ADD CONSTRAINT email_attachment_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.email(id) ON DELETE CASCADE;


--
-- Name: email_sync_state email_sync_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_sync_state
    ADD CONSTRAINT email_sync_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: email email_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email
    ADD CONSTRAINT email_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: episode_rating episode_rating_episode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode_rating
    ADD CONSTRAINT episode_rating_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES public.episode(id) ON DELETE CASCADE;


--
-- Name: episode_thread_mapping episode_thread_mapping_episode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode_thread_mapping
    ADD CONSTRAINT episode_thread_mapping_episode_id_fkey FOREIGN KEY (episode_id) REFERENCES public.episode(id) ON DELETE CASCADE;


--
-- Name: episode_thread_mapping episode_thread_mapping_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episode_thread_mapping
    ADD CONSTRAINT episode_thread_mapping_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.conversation_thread(id) ON DELETE CASCADE;


--
-- Name: event event_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: exercise_pr exercise_pr_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_pr
    ADD CONSTRAINT exercise_pr_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: fitness_idempotency fitness_idempotency_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_idempotency
    ADD CONSTRAINT fitness_idempotency_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: fitness_phase fitness_phase_parent_phase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_phase
    ADD CONSTRAINT fitness_phase_parent_phase_id_fkey FOREIGN KEY (parent_phase_id) REFERENCES public.fitness_phase(id) ON DELETE CASCADE;


--
-- Name: fitness_plan fitness_plan_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_plan
    ADD CONSTRAINT fitness_plan_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: fitness_program fitness_program_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_program
    ADD CONSTRAINT fitness_program_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: fitness_template fitness_template_phase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fitness_template
    ADD CONSTRAINT fitness_template_phase_id_fkey FOREIGN KEY (phase_id) REFERENCES public.fitness_phase(id) ON DELETE CASCADE;


--
-- Name: dev_project fk_dev_project_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dev_project
    ADD CONSTRAINT fk_dev_project_user FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: git_branch fk_git_branch_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_branch
    ADD CONSTRAINT fk_git_branch_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: git_commit fk_git_commit_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_commit
    ADD CONSTRAINT fk_git_commit_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: learning_topic fk_learning_topic_blueprint; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_topic
    ADD CONSTRAINT fk_learning_topic_blueprint FOREIGN KEY (blueprint_id) REFERENCES public.learning_blueprint(id) ON DELETE SET NULL;


--
-- Name: morning_brief fk_morning_brief_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.morning_brief
    ADD CONSTRAINT fk_morning_brief_user FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: pr_task_link fk_pr_task_link_pr; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_task_link
    ADD CONSTRAINT fk_pr_task_link_pr FOREIGN KEY (pr_id) REFERENCES public.pull_request(id) ON DELETE CASCADE;


--
-- Name: pr_task_link fk_pr_task_link_task; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_task_link
    ADD CONSTRAINT fk_pr_task_link_task FOREIGN KEY (task_id) REFERENCES public.task_item(id) ON DELETE CASCADE;


--
-- Name: project_file fk_project_file_folder; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_file
    ADD CONSTRAINT fk_project_file_folder FOREIGN KEY (folder_id) REFERENCES public.project_folder(id) ON DELETE SET NULL;


--
-- Name: project_file fk_project_file_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_file
    ADD CONSTRAINT fk_project_file_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: project_file fk_project_file_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_file
    ADD CONSTRAINT fk_project_file_user FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: project_folder fk_project_folder_parent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_folder
    ADD CONSTRAINT fk_project_folder_parent FOREIGN KEY (parent_id) REFERENCES public.project_folder(id) ON DELETE CASCADE;


--
-- Name: project_folder fk_project_folder_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_folder
    ADD CONSTRAINT fk_project_folder_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: project_folder fk_project_folder_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_folder
    ADD CONSTRAINT fk_project_folder_user FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: pull_request fk_pull_request_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_request
    ADD CONSTRAINT fk_pull_request_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: reminder fk_reminder_event_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder
    ADD CONSTRAINT fk_reminder_event_id FOREIGN KEY (event_id) REFERENCES public.calendar_event(id) ON DELETE CASCADE;


--
-- Name: shadow_event fk_shadow_event_screenshot; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_event
    ADD CONSTRAINT fk_shadow_event_screenshot FOREIGN KEY (screenshot_id) REFERENCES public.shadow_screenshot(id) ON DELETE SET NULL;


--
-- Name: shadow_session fk_shadow_session_machine; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_session
    ADD CONSTRAINT fk_shadow_session_machine FOREIGN KEY (machine_id) REFERENCES public.machine(id) ON DELETE SET NULL;


--
-- Name: task_commit_link fk_task_commit_link_commit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_commit_link
    ADD CONSTRAINT fk_task_commit_link_commit FOREIGN KEY (commit_id) REFERENCES public.git_commit(id) ON DELETE CASCADE;


--
-- Name: task_commit_link fk_task_commit_link_task; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_commit_link
    ADD CONSTRAINT fk_task_commit_link_task FOREIGN KEY (task_id) REFERENCES public.task_item(id) ON DELETE CASCADE;


--
-- Name: task_item fk_task_item_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_item
    ADD CONSTRAINT fk_task_item_project FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: task_item fk_task_item_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_item
    ADD CONSTRAINT fk_task_item_user FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_character fk_temerant_rpg_character_scene; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_character
    ADD CONSTRAINT fk_temerant_rpg_character_scene FOREIGN KEY (current_scene_id) REFERENCES public.temerant_rpg_scene(id) ON DELETE SET NULL;


--
-- Name: workout_log fk_workout_log_active_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT fk_workout_log_active_session FOREIGN KEY (active_session_id) REFERENCES public.active_workout_session(id) ON DELETE SET NULL;


--
-- Name: workout_log fk_workout_log_exercise_library; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT fk_workout_log_exercise_library FOREIGN KEY (exercise_library_id) REFERENCES public.exercise_library(id) ON DELETE SET NULL;


--
-- Name: workout_log fk_workout_log_template; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT fk_workout_log_template FOREIGN KEY (template_id) REFERENCES public.fitness_template(id) ON DELETE SET NULL;


--
-- Name: food_database food_database_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_database
    ADD CONSTRAINT food_database_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: food_log_item food_log_item_fatsecret_food_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_log_item
    ADD CONSTRAINT food_log_item_fatsecret_food_id_fkey FOREIGN KEY (fatsecret_food_id) REFERENCES public.fatsecret_food_cache(id) ON DELETE SET NULL;


--
-- Name: food_log_item food_log_item_food_log_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.food_log_item
    ADD CONSTRAINT food_log_item_food_log_id_fkey FOREIGN KEY (food_log_id) REFERENCES public.food_log(id) ON DELETE CASCADE;


--
-- Name: goal_progress goal_progress_goal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goal_progress
    ADD CONSTRAINT goal_progress_goal_id_fkey FOREIGN KEY (goal_id) REFERENCES public.goal(id) ON DELETE CASCADE;


--
-- Name: gtky_sessions gtky_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gtky_sessions
    ADD CONSTRAINT gtky_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: host_alert host_alert_host_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_alert
    ADD CONSTRAINT host_alert_host_id_fkey FOREIGN KEY (host_id) REFERENCES public.managed_host(id) ON DELETE CASCADE;


--
-- Name: host_diag_command host_diag_command_host_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_diag_command
    ADD CONSTRAINT host_diag_command_host_id_fkey FOREIGN KEY (host_id) REFERENCES public.managed_host(id) ON DELETE CASCADE;


--
-- Name: host_metric host_metric_host_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.host_metric
    ADD CONSTRAINT host_metric_host_id_fkey FOREIGN KEY (host_id) REFERENCES public.managed_host(id) ON DELETE CASCADE;


--
-- Name: hypothesis hypothesis_superseded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hypothesis
    ADD CONSTRAINT hypothesis_superseded_by_fkey FOREIGN KEY (superseded_by) REFERENCES public.hypothesis(id);


--
-- Name: insight_mention_log insight_mention_log_insight_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_mention_log
    ADD CONSTRAINT insight_mention_log_insight_id_fkey FOREIGN KEY (insight_id) REFERENCES public.dream_insight(id) ON DELETE CASCADE;


--
-- Name: insight_mention_log insight_mention_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_mention_log
    ADD CONSTRAINT insight_mention_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: intent_edge intent_edge_from_intent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intent_edge
    ADD CONSTRAINT intent_edge_from_intent_id_fkey FOREIGN KEY (from_intent_id) REFERENCES public.intent(intent_id) ON DELETE CASCADE;


--
-- Name: intent_edge intent_edge_to_intent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intent_edge
    ADD CONSTRAINT intent_edge_to_intent_id_fkey FOREIGN KEY (to_intent_id) REFERENCES public.intent(intent_id) ON DELETE CASCADE;


--
-- Name: ios_event_block ios_event_block_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ios_event_block
    ADD CONSTRAINT ios_event_block_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: jarvis_tasks jarvis_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jarvis_tasks
    ADD CONSTRAINT jarvis_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: karma_dimensions karma_dimensions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_dimensions
    ADD CONSTRAINT karma_dimensions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.karma_agents(agent_id) ON DELETE CASCADE;


--
-- Name: karma_scores karma_scores_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.karma_scores
    ADD CONSTRAINT karma_scores_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.karma_agents(agent_id) ON DELETE CASCADE;


--
-- Name: known_domain known_domain_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.known_domain
    ADD CONSTRAINT known_domain_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: known_place known_place_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.known_place
    ADD CONSTRAINT known_place_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_artifact learning_artifact_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_artifact
    ADD CONSTRAINT learning_artifact_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE SET NULL;


--
-- Name: learning_artifact learning_artifact_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_artifact
    ADD CONSTRAINT learning_artifact_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_blueprint learning_blueprint_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_blueprint
    ADD CONSTRAINT learning_blueprint_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_guide_job learning_guide_job_blueprint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_guide_job
    ADD CONSTRAINT learning_guide_job_blueprint_id_fkey FOREIGN KEY (blueprint_id) REFERENCES public.learning_blueprint(id) ON DELETE CASCADE;


--
-- Name: learning_guide_job learning_guide_job_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_guide_job
    ADD CONSTRAINT learning_guide_job_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_progress learning_progress_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_progress
    ADD CONSTRAINT learning_progress_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.topic_source(id) ON DELETE CASCADE;


--
-- Name: learning_progress learning_progress_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_progress
    ADD CONSTRAINT learning_progress_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: learning_progress learning_progress_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_progress
    ADD CONSTRAINT learning_progress_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_session learning_session_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_session
    ADD CONSTRAINT learning_session_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE SET NULL;


--
-- Name: learning_session learning_session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_session
    ADD CONSTRAINT learning_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: learning_topic learning_topic_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_topic
    ADD CONSTRAINT learning_topic_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.learning_topic(id) ON DELETE SET NULL;


--
-- Name: learning_topic learning_topic_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_topic
    ADD CONSTRAINT learning_topic_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: lesson_applications lesson_applications_lesson_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesson_applications
    ADD CONSTRAINT lesson_applications_lesson_id_fkey FOREIGN KEY (lesson_id) REFERENCES public.sara_reflection(id) ON DELETE CASCADE;


--
-- Name: location_event location_event_place_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_event
    ADD CONSTRAINT location_event_place_id_fkey FOREIGN KEY (place_id) REFERENCES public.known_place(id) ON DELETE SET NULL;


--
-- Name: location_event location_event_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_event
    ADD CONSTRAINT location_event_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: location_trigger location_trigger_place_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_trigger
    ADD CONSTRAINT location_trigger_place_id_fkey FOREIGN KEY (place_id) REFERENCES public.known_place(id) ON DELETE CASCADE;


--
-- Name: location_trigger location_trigger_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_trigger
    ADD CONSTRAINT location_trigger_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: machine machine_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine
    ADD CONSTRAINT machine_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: managed_host managed_host_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.managed_host
    ADD CONSTRAINT managed_host_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: maps maps_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maps
    ADD CONSTRAINT maps_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: ml_feature_daily ml_feature_daily_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feature_daily
    ADD CONSTRAINT ml_feature_daily_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: ml_notification_outcome ml_notification_outcome_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_notification_outcome
    ADD CONSTRAINT ml_notification_outcome_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: ml_prediction_log ml_prediction_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_prediction_log
    ADD CONSTRAINT ml_prediction_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: models_3d models_3d_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.models_3d
    ADD CONSTRAINT models_3d_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: morning_readiness morning_readiness_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.morning_readiness
    ADD CONSTRAINT morning_readiness_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: notification_log notification_log_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_log
    ADD CONSTRAINT notification_log_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_run_log(id);


--
-- Name: pattern_suggestion_log pattern_suggestion_log_pattern_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pattern_suggestion_log
    ADD CONSTRAINT pattern_suggestion_log_pattern_id_fkey FOREIGN KEY (pattern_id) REFERENCES public.behavioral_pattern(id) ON DELETE CASCADE;


--
-- Name: person person_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person
    ADD CONSTRAINT person_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: privacy_settings privacy_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privacy_settings
    ADD CONSTRAINT privacy_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: progress_photo progress_photo_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.progress_photo
    ADD CONSTRAINT progress_photo_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: project_entity_link project_entity_link_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_entity_link
    ADD CONSTRAINT project_entity_link_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id) ON DELETE CASCADE;


--
-- Name: project project_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: prompt_versions prompt_versions_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_versions
    ADD CONSTRAINT prompt_versions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.prompt_proposals(proposal_id);


--
-- Name: qa_checklist_item qa_checklist_item_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_checklist_item
    ADD CONSTRAINT qa_checklist_item_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: qa_checklist_item qa_checklist_item_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_checklist_item
    ADD CONSTRAINT qa_checklist_item_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: qa_commit_result qa_commit_result_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_commit_result
    ADD CONSTRAINT qa_commit_result_commit_id_fkey FOREIGN KEY (commit_id) REFERENCES public.git_commit(id) ON DELETE CASCADE;


--
-- Name: qa_commit_result qa_commit_result_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_commit_result
    ADD CONSTRAINT qa_commit_result_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dev_project(id) ON DELETE CASCADE;


--
-- Name: qa_commit_result qa_commit_result_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_commit_result
    ADD CONSTRAINT qa_commit_result_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: readiness_adjustments readiness_adjustments_readiness_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_adjustments
    ADD CONSTRAINT readiness_adjustments_readiness_id_fkey FOREIGN KEY (readiness_id) REFERENCES public.morning_readiness(id) ON DELETE CASCADE;


--
-- Name: readiness_adjustments readiness_adjustments_workout_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_adjustments
    ADD CONSTRAINT readiness_adjustments_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES public.workout(id) ON DELETE CASCADE;


--
-- Name: reflection_settings reflection_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reflection_settings
    ADD CONSTRAINT reflection_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: research_job research_job_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_job
    ADD CONSTRAINT research_job_report_id_fkey FOREIGN KEY (report_id) REFERENCES public.research_report(id) ON DELETE CASCADE;


--
-- Name: research_job research_job_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_job
    ADD CONSTRAINT research_job_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: research_message research_message_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_message
    ADD CONSTRAINT research_message_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.research_plan(id) ON DELETE CASCADE;


--
-- Name: research_report research_report_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_report
    ADD CONSTRAINT research_report_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE SET NULL;


--
-- Name: research_report research_report_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_report
    ADD CONSTRAINT research_report_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: sara_reflection sara_reflection_superseded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_reflection
    ADD CONSTRAINT sara_reflection_superseded_by_fkey FOREIGN KEY (superseded_by) REFERENCES public.sara_reflection(id);


--
-- Name: sara_tool sara_tool_active_version_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool
    ADD CONSTRAINT sara_tool_active_version_fk FOREIGN KEY (active_version_id) REFERENCES public.sara_tool_version(id) ON DELETE SET NULL;


--
-- Name: sara_tool_invocation sara_tool_invocation_tool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_invocation
    ADD CONSTRAINT sara_tool_invocation_tool_id_fkey FOREIGN KEY (tool_id) REFERENCES public.sara_tool(id) ON DELETE CASCADE;


--
-- Name: sara_tool_invocation sara_tool_invocation_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_invocation
    ADD CONSTRAINT sara_tool_invocation_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.sara_tool_version(id) ON DELETE CASCADE;


--
-- Name: sara_tool_version sara_tool_version_tool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sara_tool_version
    ADD CONSTRAINT sara_tool_version_tool_id_fkey FOREIGN KEY (tool_id) REFERENCES public.sara_tool(id) ON DELETE CASCADE;


--
-- Name: saved_meal saved_meal_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_meal
    ADD CONSTRAINT saved_meal_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: scheduled_home_action scheduled_home_action_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_home_action
    ADD CONSTRAINT scheduled_home_action_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: semantic_summary semantic_summary_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.semantic_summary
    ADD CONSTRAINT semantic_summary_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: shadow_event shadow_event_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_event
    ADD CONSTRAINT shadow_event_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.shadow_session(id) ON DELETE CASCADE;


--
-- Name: shadow_note shadow_note_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_note
    ADD CONSTRAINT shadow_note_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.shadow_session(id) ON DELETE CASCADE;


--
-- Name: shadow_screenshot shadow_screenshot_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_screenshot
    ADD CONSTRAINT shadow_screenshot_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.shadow_session(id) ON DELETE CASCADE;


--
-- Name: shadow_session shadow_session_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_session
    ADD CONSTRAINT shadow_session_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: shadow_session shadow_session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_session
    ADD CONSTRAINT shadow_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: shadow_summary shadow_summary_committed_note_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_summary
    ADD CONSTRAINT shadow_summary_committed_note_id_fkey FOREIGN KEY (committed_note_id) REFERENCES public.note(id) ON DELETE SET NULL;


--
-- Name: shadow_summary shadow_summary_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_summary
    ADD CONSTRAINT shadow_summary_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.shadow_session(id) ON DELETE CASCADE;


--
-- Name: shared_content shared_content_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_content
    ADD CONSTRAINT shared_content_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: source_chunk source_chunk_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunk
    ADD CONSTRAINT source_chunk_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.topic_source(id) ON DELETE CASCADE;


--
-- Name: surface surface_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.surface
    ADD CONSTRAINT surface_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: tangent_queue tangent_queue_parent_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tangent_queue
    ADD CONSTRAINT tangent_queue_parent_topic_id_fkey FOREIGN KEY (parent_topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: tangent_queue tangent_queue_promoted_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tangent_queue
    ADD CONSTRAINT tangent_queue_promoted_topic_id_fkey FOREIGN KEY (promoted_topic_id) REFERENCES public.learning_topic(id) ON DELETE SET NULL;


--
-- Name: tangent_queue tangent_queue_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tangent_queue
    ADD CONSTRAINT tangent_queue_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_attribute_state temerant_attribute_state_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_attribute_state
    ADD CONSTRAINT temerant_attribute_state_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_character temerant_character_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_character
    ADD CONSTRAINT temerant_character_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_daily_state temerant_daily_state_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_daily_state
    ADD CONSTRAINT temerant_daily_state_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_daily_state temerant_daily_state_oracle_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_daily_state
    ADD CONSTRAINT temerant_daily_state_oracle_event_id_fkey FOREIGN KEY (oracle_event_id) REFERENCES public.temerant_oracle_event(id) ON DELETE SET NULL;


--
-- Name: temerant_daily_state temerant_daily_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_daily_state
    ADD CONSTRAINT temerant_daily_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_ingestion_cursor temerant_ingestion_cursor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_ingestion_cursor
    ADD CONSTRAINT temerant_ingestion_cursor_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_journal_entry temerant_journal_entry_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_journal_entry
    ADD CONSTRAINT temerant_journal_entry_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_journal_entry temerant_journal_entry_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_journal_entry
    ADD CONSTRAINT temerant_journal_entry_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_mapping_rule temerant_mapping_rule_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_mapping_rule
    ADD CONSTRAINT temerant_mapping_rule_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_masterwork temerant_masterwork_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_masterwork
    ADD CONSTRAINT temerant_masterwork_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_masterwork temerant_masterwork_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_masterwork
    ADD CONSTRAINT temerant_masterwork_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_oracle_event temerant_oracle_event_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_oracle_event
    ADD CONSTRAINT temerant_oracle_event_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_oracle_event temerant_oracle_event_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_oracle_event
    ADD CONSTRAINT temerant_oracle_event_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.temerant_story_thread(id) ON DELETE SET NULL;


--
-- Name: temerant_oracle_event temerant_oracle_event_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_oracle_event
    ADD CONSTRAINT temerant_oracle_event_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_character temerant_rpg_character_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_character
    ADD CONSTRAINT temerant_rpg_character_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_journal_entry temerant_rpg_journal_entry_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_journal_entry
    ADD CONSTRAINT temerant_rpg_journal_entry_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_rpg_character(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_journal_entry temerant_rpg_journal_entry_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_journal_entry
    ADD CONSTRAINT temerant_rpg_journal_entry_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_relationship temerant_rpg_relationship_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_relationship
    ADD CONSTRAINT temerant_rpg_relationship_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_rpg_character(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_relationship temerant_rpg_relationship_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_relationship
    ADD CONSTRAINT temerant_rpg_relationship_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_scene temerant_rpg_scene_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene
    ADD CONSTRAINT temerant_rpg_scene_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_rpg_character(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_scene_turn temerant_rpg_scene_turn_scene_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene_turn
    ADD CONSTRAINT temerant_rpg_scene_turn_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES public.temerant_rpg_scene(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_scene_turn temerant_rpg_scene_turn_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene_turn
    ADD CONSTRAINT temerant_rpg_scene_turn_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_scene temerant_rpg_scene_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_scene
    ADD CONSTRAINT temerant_rpg_scene_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_term temerant_rpg_term_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_term
    ADD CONSTRAINT temerant_rpg_term_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_rpg_character(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_term temerant_rpg_term_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_term
    ADD CONSTRAINT temerant_rpg_term_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_world_state temerant_rpg_world_state_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_world_state
    ADD CONSTRAINT temerant_rpg_world_state_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_rpg_character(id) ON DELETE CASCADE;


--
-- Name: temerant_rpg_world_state temerant_rpg_world_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_rpg_world_state
    ADD CONSTRAINT temerant_rpg_world_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_story_thread temerant_story_thread_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_story_thread
    ADD CONSTRAINT temerant_story_thread_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_story_thread temerant_story_thread_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_story_thread
    ADD CONSTRAINT temerant_story_thread_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_term temerant_term_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_term
    ADD CONSTRAINT temerant_term_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_term temerant_term_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_term
    ADD CONSTRAINT temerant_term_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: temerant_xp_ledger temerant_xp_ledger_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_xp_ledger
    ADD CONSTRAINT temerant_xp_ledger_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.temerant_character(id) ON DELETE CASCADE;


--
-- Name: temerant_xp_ledger temerant_xp_ledger_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temerant_xp_ledger
    ADD CONSTRAINT temerant_xp_ledger_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: template_exercise template_exercise_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_exercise
    ADD CONSTRAINT template_exercise_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.fitness_template(id) ON DELETE CASCADE;


--
-- Name: token_usage_aggregate token_usage_aggregate_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage_aggregate
    ADD CONSTRAINT token_usage_aggregate_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: token_usage token_usage_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT token_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: topic_connection topic_connection_source_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_connection
    ADD CONSTRAINT topic_connection_source_topic_id_fkey FOREIGN KEY (source_topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: topic_connection topic_connection_target_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_connection
    ADD CONSTRAINT topic_connection_target_topic_id_fkey FOREIGN KEY (target_topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: topic_connection topic_connection_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_connection
    ADD CONSTRAINT topic_connection_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: topic_scratchpad topic_scratchpad_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_scratchpad
    ADD CONSTRAINT topic_scratchpad_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: topic_scratchpad topic_scratchpad_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_scratchpad
    ADD CONSTRAINT topic_scratchpad_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: topic_source topic_source_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_source
    ADD CONSTRAINT topic_source_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.learning_topic(id) ON DELETE CASCADE;


--
-- Name: topic_source topic_source_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_source
    ADD CONSTRAINT topic_source_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_activity_log user_activity_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_activity_log
    ADD CONSTRAINT user_activity_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_relationship user_relationship_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_relationship
    ADD CONSTRAINT user_relationship_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_settings user_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: voice_interaction_log voice_interaction_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_interaction_log
    ADD CONSTRAINT voice_interaction_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: weight_trend weight_trend_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weight_trend
    ADD CONSTRAINT weight_trend_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: workout workout_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout
    ADD CONSTRAINT workout_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: workout_log workout_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT workout_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: workout_log workout_log_workout_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_log
    ADD CONSTRAINT workout_log_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES public.workout(id) ON DELETE CASCADE;


--
-- Name: workout workout_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout
    ADD CONSTRAINT workout_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.fitness_plan(id) ON DELETE CASCADE;


--
-- Name: workout_session workout_session_active_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout_session
    ADD CONSTRAINT workout_session_active_session_id_fkey FOREIGN KEY (active_session_id) REFERENCES public.active_workout_session(id) ON DELETE SET NULL;


--
-- Name: workout workout_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workout
    ADD CONSTRAINT workout_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: workspace_job workspace_job_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_job
    ADD CONSTRAINT workspace_job_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: workspace_states workspace_states_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_states
    ADD CONSTRAINT workspace_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: world_event_disposition world_event_disposition_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_disposition
    ADD CONSTRAINT world_event_disposition_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.world_event(event_id) ON DELETE CASCADE;


--
-- Name: world_event_processing world_event_processing_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.world_event_processing
    ADD CONSTRAINT world_event_processing_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.world_event(event_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict wqEwBaDybiH7Y8UCbf661FBZVd0M74UcU3L8djU5r2LavnDjiuFlKEby8XtGnXy

