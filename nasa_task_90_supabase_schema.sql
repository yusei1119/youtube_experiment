-- NASA_task_90 専用 Supabase スキーマ
-- Supabase Dashboard > SQL Editor で実行してください。

create extension if not exists pgcrypto;

create table if not exists public.nasa_90_submissions (
  id uuid primary key default gen_random_uuid(),
  survey_id text not null,
  participant_id text not null,
  video_condition text not null check (video_condition in ('short', 'med', 'control')),
  condition_order smallint not null check (condition_order between 1 and 3),
  total_conditions smallint not null default 3 check (total_conditions = 3),
  page_session_id text not null,
  started_at timestamptz not null,
  completed_at timestamptz not null,
  total_duration_sec double precision not null check (total_duration_sec >= 0),
  raw_tlx_sum integer not null check (raw_tlx_sum between 0 and 600),
  raw_tlx_mean double precision not null check (raw_tlx_mean between 0 and 100),
  overall_workload integer not null check (overall_workload between 0 and 100),
  user_agent text,
  created_at timestamptz not null default now(),
  unique (survey_id, participant_id, condition_order),
  unique (survey_id, participant_id, video_condition)
);

create table if not exists public.nasa_90_responses (
  id bigint generated always as identity primary key,
  submission_id uuid not null references public.nasa_90_submissions(id) on delete cascade,
  question_id text not null,
  dimension_key text not null check (
    dimension_key in ('mental', 'physical', 'temporal', 'performance', 'effort', 'frustration', 'overall')
  ),
  dimension_label text not null,
  display_order smallint not null check (display_order between 1 and 7),
  question_text text not null,
  slider_value integer not null check (slider_value between 0 and 100),
  first_shown_sec double precision not null check (first_shown_sec >= 0),
  latency_to_first_input_sec double precision check (latency_to_first_input_sec >= 0),
  cumulative_duration_sec double precision not null check (cumulative_duration_sec >= 0),
  visits integer not null check (visits > 0),
  revision_count integer not null check (revision_count >= 0),
  unique (submission_id, dimension_key),
  unique (submission_id, display_order)
);

create index if not exists idx_nasa_90_participant
  on public.nasa_90_submissions (participant_id);
create index if not exists idx_nasa_90_condition
  on public.nasa_90_submissions (video_condition);
create index if not exists idx_nasa_90_responses_submission
  on public.nasa_90_responses (submission_id);

comment on column public.nasa_90_submissions.raw_tlx_mean is
  '精神的要求・身体的要求・時間的要求・パフォーマンス・努力・フラストレーションの単純平均（0～100）';
comment on column public.nasa_90_submissions.overall_workload is
  '追加項目「全体的負荷」の回答値（Raw TLX平均には含めない）';
comment on column public.nasa_90_responses.cumulative_duration_sec is
  '項目表示から次へ/戻るまでの時間を訪問ごとに合算（修正時の再訪を含む）';
comment on column public.nasa_90_responses.latency_to_first_input_sec is
  '各訪問で項目表示から最初にスライダーを操作するまでの時間の合計';

alter table public.nasa_90_submissions enable row level security;
alter table public.nasa_90_responses enable row level security;

create or replace function public.submit_nasa_90_survey(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  new_submission_id uuid;
  response_count integer;
  calculated_sum integer;
  calculated_overall integer;
begin
  if payload is null or jsonb_typeof(payload) <> 'object' then
    raise exception 'payload must be a JSON object';
  end if;

  response_count := jsonb_array_length(coalesce(payload->'responses', '[]'::jsonb));
  if response_count <> 7 then
    raise exception 'exactly 7 responses are required';
  end if;

  select
    sum((item->>'slider_value')::integer) filter (where item->>'dimension_key' <> 'overall'),
    max((item->>'slider_value')::integer) filter (where item->>'dimension_key' = 'overall')
  into calculated_sum, calculated_overall
  from jsonb_array_elements(payload->'responses') as item;

  if calculated_sum is null or calculated_overall is null then
    raise exception 'standard dimensions and overall workload are required';
  end if;

  insert into public.nasa_90_submissions (
    survey_id, participant_id, video_condition, condition_order, total_conditions,
    page_session_id, started_at, completed_at, total_duration_sec,
    raw_tlx_sum, raw_tlx_mean, overall_workload, user_agent
  ) values (
    nullif(btrim(payload->>'survey_id'), ''),
    nullif(btrim(payload->>'participant_id'), ''),
    nullif(payload->>'video_condition', ''),
    (payload->>'condition_order')::smallint,
    (payload->>'total_conditions')::smallint,
    nullif(payload->>'page_session_id', ''),
    (payload->>'started_at')::timestamptz,
    (payload->>'completed_at')::timestamptz,
    (payload->>'total_duration_sec')::double precision,
    calculated_sum,
    calculated_sum / 6.0,
    calculated_overall,
    payload->>'user_agent'
  ) returning id into new_submission_id;

  insert into public.nasa_90_responses (
    submission_id, question_id, dimension_key, dimension_label, display_order,
    question_text, slider_value, first_shown_sec, latency_to_first_input_sec,
    cumulative_duration_sec, visits, revision_count
  )
  select
    new_submission_id,
    nullif(btrim(item->>'question_id'), ''),
    nullif(item->>'dimension_key', ''),
    nullif(item->>'dimension_label', ''),
    (item->>'display_order')::smallint,
    nullif(item->>'question_text', ''),
    (item->>'slider_value')::integer,
    (item->>'first_shown_sec')::double precision,
    nullif(item->>'latency_to_first_input_sec', '')::double precision,
    (item->>'cumulative_duration_sec')::double precision,
    (item->>'visits')::integer,
    (item->>'revision_count')::integer
  from jsonb_array_elements(payload->'responses') as item;

  return new_submission_id;
end;
$$;

revoke all on function public.submit_nasa_90_survey(jsonb) from public;
grant execute on function public.submit_nasa_90_survey(jsonb) to anon, authenticated;
revoke all on table public.nasa_90_submissions from anon, authenticated;
revoke all on table public.nasa_90_responses from anon, authenticated;

notify pgrst, 'reload schema';
