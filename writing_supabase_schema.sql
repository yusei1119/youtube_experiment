-- 記述課題用 Supabase スキーマ
-- Supabase Dashboard > SQL Editor で実行してください。
-- 既存テーブルを削除せず、安全に追加・更新できます。

create extension if not exists pgcrypto;

create table if not exists public.writing_submissions (
  id uuid primary key default gen_random_uuid(),
  survey_id text not null,
  participant_id text not null,
  video_condition text not null check (
    video_condition in ('short', 'med', 'control')
  ),
  questionnaire_number smallint not null check (questionnaire_number between 1 and 3),
  total_questionnaires smallint not null default 3 check (total_questionnaires = 3),
  condition_number smallint not null check (condition_number between 1 and 3),
  assignment_seed text not null,
  page_randomization_id text not null,
  started_at timestamptz not null,
  completed_at timestamptz not null,
  total_duration_sec double precision not null check (total_duration_sec >= 0),
  user_agent text,
  created_at timestamptz not null default now(),
  constraint uq_writing_submission_round
    unique (survey_id, participant_id, questionnaire_number)
);

-- 旧版スキーマを実行済みの場合の移行処理。
alter table public.writing_submissions
  add column if not exists video_condition text;
alter table public.writing_submissions
  add column if not exists questionnaire_number smallint;
alter table public.writing_submissions
  add column if not exists total_questionnaires smallint default 3;
alter table public.writing_submissions
  add column if not exists page_randomization_id text;

-- 旧版の条件名を変換できるよう、旧チェック制約を先に外す。
alter table public.writing_submissions
  drop constraint if exists writing_submissions_video_condition_check;
alter table public.writing_submissions
  drop constraint if exists chk_writing_video_condition;

update public.writing_submissions
set questionnaire_number = coalesce(questionnaire_number, condition_number, 1),
    total_questionnaires = coalesce(total_questionnaires, 3),
    page_randomization_id = coalesce(page_randomization_id, assignment_seed, 'legacy'),
    video_condition = case
      when video_condition = 'short_video' then 'short'
      when video_condition = 'meditation_video' then 'med'
      when video_condition = 'daily_video' then 'control'
      else coalesce(video_condition, 'short')
    end
where questionnaire_number is null
   or total_questionnaires is null
   or page_randomization_id is null
   or video_condition is null;

alter table public.writing_submissions
  alter column questionnaire_number set not null,
  alter column total_questionnaires set not null,
  alter column page_randomization_id set not null,
  alter column video_condition set not null;

-- 旧版の「参加者につき1回」の制約を外し、3アンケートを別々に保存可能にする。
alter table public.writing_submissions
  drop constraint if exists writing_submissions_survey_id_participant_id_key;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'uq_writing_submission_round'
      and conrelid = 'public.writing_submissions'::regclass
  ) then
    alter table public.writing_submissions
      add constraint uq_writing_submission_round
      unique (survey_id, participant_id, questionnaire_number);
  end if;
end;
$$;

do $$
begin
  alter table public.writing_submissions
    add constraint chk_writing_video_condition check (
      video_condition in ('short', 'med', 'control')
    );
end;
$$;

create table if not exists public.writing_responses (
  id bigint generated always as identity primary key,
  submission_id uuid not null references public.writing_submissions(id) on delete cascade,
  question_id text not null,
  display_order smallint not null check (display_order > 0),
  category_key text not null,
  category_label text not null,
  variant_number smallint not null check (variant_number between 1 and 3),
  question_text text not null,
  answer_text text not null,
  first_shown_sec double precision not null check (first_shown_sec >= 0),
  latency_to_first_input_sec double precision check (latency_to_first_input_sec >= 0),
  cumulative_duration_sec double precision not null check (cumulative_duration_sec >= 0),
  visits integer not null check (visits > 0),
  revision_count integer not null check (revision_count >= 0),
  unique (submission_id, question_id),
  unique (submission_id, display_order)
);

create index if not exists idx_writing_submissions_participant
  on public.writing_submissions (participant_id);
create index if not exists idx_writing_submissions_questionnaire
  on public.writing_submissions (survey_id, questionnaire_number);
create index if not exists idx_writing_submissions_video_condition
  on public.writing_submissions (survey_id, video_condition);
create index if not exists idx_writing_responses_submission
  on public.writing_responses (submission_id);

alter table public.writing_submissions enable row level security;
alter table public.writing_responses enable row level security;

-- ブラウザにはテーブルの直接操作権限を与えず、この関数だけを公開する。
create or replace function public.submit_writing_survey(payload jsonb)
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
    select 1
    from public.writing_submissions
    where survey_id = payload->>'survey_id'
      and participant_id = payload->>'participant_id'
      and video_condition = payload->>'video_condition'
  ) then
    raise exception 'this participant has already submitted the selected condition';
  end if;

  insert into public.writing_submissions (
    survey_id, participant_id, video_condition, questionnaire_number, total_questionnaires,
    condition_number, assignment_seed, page_randomization_id,
    started_at, completed_at, total_duration_sec, user_agent
  ) values (
    nullif(btrim(payload->>'survey_id'), ''),
    nullif(btrim(payload->>'participant_id'), ''),
    nullif(payload->>'video_condition', ''),
    (payload->>'questionnaire_number')::smallint,
    (payload->>'total_questionnaires')::smallint,
    (payload->>'condition_number')::smallint,
    nullif(payload->>'assignment_seed', ''),
    nullif(payload->>'page_randomization_id', ''),
    (payload->>'started_at')::timestamptz,
    (payload->>'completed_at')::timestamptz,
    (payload->>'total_duration_sec')::double precision,
    payload->>'user_agent'
  )
  returning id into new_submission_id;

  insert into public.writing_responses (
    submission_id, question_id, display_order, category_key, category_label,
    variant_number, question_text, answer_text, first_shown_sec,
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
    (item->>'first_shown_sec')::double precision,
    nullif(item->>'latency_to_first_input_sec', '')::double precision,
    (item->>'cumulative_duration_sec')::double precision,
    (item->>'visits')::integer,
    (item->>'revision_count')::integer
  from jsonb_array_elements(payload->'responses') as item;

  return new_submission_id;
end;
$$;

revoke all on function public.submit_writing_survey(jsonb) from public;
grant execute on function public.submit_writing_survey(jsonb) to anon, authenticated;

-- CSV出力には service_role key を使うため、匿名ユーザーのSELECT権限は不要。
revoke all on table public.writing_submissions from anon, authenticated;
revoke all on table public.writing_responses from anon, authenticated;

notify pgrst, 'reload schema';
