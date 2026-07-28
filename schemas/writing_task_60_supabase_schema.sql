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
  total_answer_duration_sec double precision not null check (total_answer_duration_sec >= 0),
  total_char_count integer not null check (total_char_count >= 0),
  user_agent text,
  created_at timestamptz not null default now()
);

-- 同じ参加者IDによる複数回の回答を許可する。
alter table public.writing_60_submissions
  drop constraint if exists writing_60_submissions_survey_id_participant_id_key;
do $$
declare constraint_row record;
begin
  for constraint_row in
    select conname from pg_constraint
    where contype = 'u'
      and conrelid = 'public.writing_60_submissions'::regclass
      and pg_get_constraintdef(oid) like '%participant_id%'
  loop
    execute format('alter table public.writing_60_submissions drop constraint %I', constraint_row.conname);
  end loop;
end;
$$;

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
  latency_sec double precision not null check (latency_sec >= 0),
  writing_duration_sec double precision not null check (writing_duration_sec >= 0),
  visits integer not null check (visits > 0),
  revision_count integer not null check (revision_count >= 0),
  unique (submission_id, question_id),
  unique (submission_id, display_order)
);

alter table public.writing_60_submissions
  add column if not exists total_answer_duration_sec double precision
  check (total_answer_duration_sec >= 0);

-- 旧指標を新指標へ変換する。旧cumulativeはlatencyを含むため差し引く。
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'writing_60_responses'
      and column_name = 'latency_to_first_input_sec'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'writing_60_responses'
      and column_name = 'latency_sec'
  ) then
    alter table public.writing_60_responses
      rename column latency_to_first_input_sec to latency_sec;
  end if;

  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'writing_60_responses'
      and column_name = 'cumulative_duration_sec'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'writing_60_responses'
      and column_name = 'writing_duration_sec'
  ) then
    alter table public.writing_60_responses
      rename column cumulative_duration_sec to writing_duration_sec;
    update public.writing_60_responses
    set writing_duration_sec = greatest(
      writing_duration_sec - coalesce(latency_sec, 0),
      0
    );
  end if;
end;
$$;

update public.writing_60_responses
set latency_sec = 0
where latency_sec is null;

alter table public.writing_60_responses
  alter column latency_sec set not null;

update public.writing_60_submissions submission
set total_answer_duration_sec = totals.total_answer_duration_sec
from (
  select submission_id,
         sum(latency_sec + writing_duration_sec) as total_answer_duration_sec
  from public.writing_60_responses
  group by submission_id
) totals
where submission.id = totals.submission_id
  and submission.total_answer_duration_sec is null;

update public.writing_60_submissions
set total_answer_duration_sec = 0
where total_answer_duration_sec is null;

alter table public.writing_60_submissions
  alter column total_answer_duration_sec set not null;

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

comment on column public.writing_60_responses.writing_duration_sec is
  '各訪問の初回入力後から次へ/戻るまでの記述時間の合計（修正訪問を含む）';
comment on column public.writing_60_responses.latency_sec is
  '各訪問で質問表示から最初に入力するまでの時間の合計（入力なしの再訪は訪問全体）';
comment on column public.writing_60_submissions.total_answer_duration_sec is
  '5問分のlatency_secとwriting_duration_secの合計。確認画面・送信時間は含まない';
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

  insert into public.writing_60_submissions (
    survey_id, participant_id, viewing_duration, questionnaire_number,
    total_questionnaires, assignment_seed, page_randomization_id,
    started_at, completed_at, total_duration_sec, total_answer_duration_sec,
    total_char_count, user_agent
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
      select sum(
        coalesce((item->>'latency_sec')::double precision, 0)
        + (item->>'writing_duration_sec')::double precision
      )
      from jsonb_array_elements(payload->'responses') as item
    ),
    (
      select sum(char_length(btrim(item->>'answer_text')))::integer
      from jsonb_array_elements(payload->'responses') as item
    ),
    payload->>'user_agent'
  ) returning id into new_submission_id;

  insert into public.writing_60_responses (
    submission_id, question_id, display_order, category_key, category_label,
    variant_number, question_text, answer_text, answer_char_count, first_shown_sec,
    latency_sec, writing_duration_sec, visits, revision_count
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
    coalesce(nullif(item->>'latency_sec', '')::double precision, 0),
    (item->>'writing_duration_sec')::double precision,
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
