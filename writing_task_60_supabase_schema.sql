-- Writing_task_60 専用 Supabase スキーマ
-- Supabase Dashboard > SQL Editor で実行してください。

create extension if not exists pgcrypto;

create table if not exists public.writing_60_submissions (
  id uuid primary key default gen_random_uuid(),
  survey_id text not null,
  participant_id text not null,
  viewing_duration text not null check (
    viewing_duration in ('5min', '10min', '15min', '20min', '25min', '30min')
  ),
  questionnaire_number smallint not null default 1 check (questionnaire_number = 1),
  total_questionnaires smallint not null default 1 check (total_questionnaires = 1),
  assignment_seed text not null,
  page_randomization_id text not null,
  started_at timestamptz not null,
  completed_at timestamptz not null,
  total_duration_sec double precision not null check (total_duration_sec >= 0),
  total_char_count integer not null check (total_char_count >= 0),
  user_agent text,
  created_at timestamptz not null default now(),
  unique (survey_id, participant_id)
);

create table if not exists public.writing_60_responses (
  id bigint generated always as identity primary key,
  submission_id uuid not null references public.writing_60_submissions(id) on delete cascade,
  question_id text not null,
  display_order smallint not null check (display_order > 0),
  category_key text not null,
  category_label text not null,
  variant_number smallint not null check (variant_number between 1 and 3),
  question_text text not null,
  answer_text text not null,
  answer_char_count integer not null check (answer_char_count >= 0),
  first_shown_sec double precision not null check (first_shown_sec >= 0),
  latency_to_first_input_sec double precision check (latency_to_first_input_sec >= 0),
  cumulative_duration_sec double precision not null check (cumulative_duration_sec >= 0),
  visits integer not null check (visits > 0),
  revision_count integer not null check (revision_count >= 0),
  unique (submission_id, question_id),
  unique (submission_id, display_order)
);

-- 旧版（variant_number = 1固定）を実行済みの場合も3種類を保存可能にする。
alter table public.writing_60_responses
  drop constraint if exists writing_60_responses_variant_number_check;
alter table public.writing_60_responses
  drop constraint if exists chk_writing_60_variant_number;
alter table public.writing_60_responses
  add constraint chk_writing_60_variant_number
  check (variant_number between 1 and 3);

create index if not exists idx_writing_60_participant
  on public.writing_60_submissions (participant_id);
create index if not exists idx_writing_60_duration
  on public.writing_60_submissions (viewing_duration);
create index if not exists idx_writing_60_responses_submission
  on public.writing_60_responses (submission_id);

comment on column public.writing_60_responses.cumulative_duration_sec is
  '質問画面の表示から次へ/戻るまでの時間を訪問ごとに合算した回答時間（修正時の再訪を含む）';
comment on column public.writing_60_responses.latency_to_first_input_sec is
  '各訪問で質問表示から最初に入力するまでの時間の合計（修正訪問を含む）';
comment on column public.writing_60_responses.answer_char_count is
  '回答のUnicode文字数（先頭末尾の空白を除き、回答内の空白・改行・句読点を含む）';
comment on column public.writing_60_submissions.total_char_count is
  '5問分のanswer_char_count合計';

alter table public.writing_60_submissions enable row level security;
alter table public.writing_60_responses enable row level security;

create or replace function public.submit_writing_60_survey(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  new_submission_id uuid;
  response_count integer;
begin
  if payload is null or jsonb_typeof(payload) <> 'object' then
    raise exception 'payload must be a JSON object';
  end if;

  response_count := jsonb_array_length(coalesce(payload->'responses', '[]'::jsonb));
  if response_count <> 5 then
    raise exception 'exactly 5 responses are required';
  end if;

  if exists (
    select 1 from public.writing_60_submissions
    where survey_id = payload->>'survey_id'
      and participant_id = payload->>'participant_id'
  ) then
    raise exception 'this participant has already submitted';
  end if;

  insert into public.writing_60_submissions (
    survey_id, participant_id, viewing_duration, questionnaire_number,
    total_questionnaires, assignment_seed, page_randomization_id,
    started_at, completed_at, total_duration_sec, total_char_count, user_agent
  ) values (
    nullif(btrim(payload->>'survey_id'), ''),
    nullif(btrim(payload->>'participant_id'), ''),
    nullif(payload->>'viewing_duration', ''),
    (payload->>'questionnaire_number')::smallint,
    (payload->>'total_questionnaires')::smallint,
    nullif(payload->>'assignment_seed', ''),
    nullif(payload->>'page_randomization_id', ''),
    (payload->>'started_at')::timestamptz,
    (payload->>'completed_at')::timestamptz,
    (payload->>'total_duration_sec')::double precision,
    (
      select sum(char_length(btrim(item->>'answer_text')))::integer
      from jsonb_array_elements(payload->'responses') as item
    ),
    payload->>'user_agent'
  ) returning id into new_submission_id;

  insert into public.writing_60_responses (
    submission_id, question_id, display_order, category_key, category_label,
    variant_number, question_text, answer_text, answer_char_count, first_shown_sec,
    latency_to_first_input_sec, cumulative_duration_sec, visits, revision_count
  )
  select
    new_submission_id,
    nullif(btrim(item->>'question_id'), ''),
    (item->>'display_order')::smallint,
    nullif(item->>'category_key', ''),
    nullif(item->>'category_label', ''),
    (item->>'variant_number')::smallint,
    nullif(item->>'question_text', ''),
    nullif(btrim(item->>'answer_text'), ''),
    char_length(nullif(btrim(item->>'answer_text'), '')),
    (item->>'first_shown_sec')::double precision,
    nullif(item->>'latency_to_first_input_sec', '')::double precision,
    (item->>'cumulative_duration_sec')::double precision,
    (item->>'visits')::integer,
    (item->>'revision_count')::integer
  from jsonb_array_elements(payload->'responses') as item;

  return new_submission_id;
end;
$$;

revoke all on function public.submit_writing_60_survey(jsonb) from public;
grant execute on function public.submit_writing_60_survey(jsonb) to anon, authenticated;
revoke all on table public.writing_60_submissions from anon, authenticated;
revoke all on table public.writing_60_responses from anon, authenticated;

notify pgrst, 'reload schema';
