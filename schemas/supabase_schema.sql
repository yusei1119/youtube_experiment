-- ============================================================================
-- YouTube視聴実験 Supabase スキーマ
--   experiment_sessions / view_logs テーブルの再作成と、
--   分析用ビュー（video_summary / participant_summary）を定義する。
--
-- 使い方: Supabase ダッシュボード > SQL Editor にこのファイルを貼り付けて実行。
--   何度実行しても同じ状態になる（drop → create）。既存データは消えるので注意。
-- ============================================================================

-- ---- 後片付け（依存関係の逆順で削除） --------------------------------------
drop view if exists participant_summary;
drop view if exists video_summary;
drop table if exists view_logs;
drop table if exists experiment_sessions;

-- ---- セッション（参加者1回の視聴 = 1行） -----------------------------------
create table experiment_sessions (
  id            uuid primary key,
  participant_id text not null,
  playlist_id   text,
  video_count   integer,
  video_order   jsonb,                 -- シャッフル済みの動画リスト
  current_index integer default 0,
  started_at    timestamptz,
  finished_at   timestamptz,
  updated_at    timestamptz
);

create index idx_sessions_participant on experiment_sessions (participant_id);

-- ---- 視聴ログ（イベント1件 = 1行） -----------------------------------------
create table view_logs (
  id               uuid primary key,
  server_time      timestamptz,
  participant_id   text,
  session_id       uuid references experiment_sessions (id) on delete cascade,
  playlist_id      text,
  video_id         text,
  video_title      text,
  video_index      integer,
  event_type       text,
  current_time_sec double precision,
  duration_sec     double precision,
  progress_rate    double precision,
  max_time_sec     double precision,   -- その動画で最も先まで見た位置（≒視聴秒数）
  playback_rate    double precision,
  muted            boolean,
  volume           double precision,
  visibility_state text,
  window_focused   boolean,
  user_agent       text
);

-- 分析クエリでよく使う列にインデックス
create index idx_logs_session    on view_logs (session_id);
create index idx_logs_participant on view_logs (participant_id);
create index idx_logs_event      on view_logs (event_type);
create index idx_logs_video      on view_logs (session_id, video_index);
create index idx_logs_time       on view_logs (server_time);

-- ============================================================================
-- 分析ビュー
-- ============================================================================

-- ---- しきい値（変更したい場合はこの2か所の数値を直す） ----------------------
--   視聴完了とみなす到達率 : 0.9
--   早期スキップの視聴秒数上限 : 2.0

-- ---- 動画レベル（参加者 × セッション × 動画 = 1行） ------------------------
create view video_summary as
with base as (
  select
    l.participant_id,
    l.session_id,
    l.video_index,
    min(l.video_id)    as video_id,
    min(l.video_title) as video_title,
    max(s.video_order -> l.video_index ->> 'category_id')    as video_category_id,
    max(s.video_order -> l.video_index ->> 'category_title') as video_category,
    max(l.max_time_sec)  as watched_sec,   -- 最も先まで見た位置
    max(l.duration_sec)  as duration_sec,
    min(l.server_time)   as first_time,
    max(l.server_time)   as last_time,
    bool_or(l.event_type = 'ended') as has_ended,
    count(*) as log_count
  from view_logs l
  left join experiment_sessions s on s.id = l.session_id
  group by l.participant_id, l.session_id, l.video_index
),
calc as (
  select
    *,
    case when duration_sec > 0
         then least(coalesce(watched_sec, 0) / duration_sec, 1.0)
    end as view_rate
  from base
)
select
  *,
  (coalesce(view_rate, 0) >= 0.9 or has_ended)                                as completed,
  (coalesce(watched_sec, 0) <= 2.0
     and not (coalesce(view_rate, 0) >= 0.9 or has_ended))                    as early_skip
from calc;

-- ---- 参加者レベル（参加者 × セッション = 1行、統計分析の解析単位） ---------
create view participant_summary as
with v as (
  select * from video_summary
),
ordered as (
  -- 視聴順（video_index 昇順）に番号付けし、連続スキップ判定用の島(grp)も作る
  select
    *,
    row_number() over (partition by participant_id, session_id order by video_index) as rn,
    count(*)     over (partition by participant_id, session_id)                      as n,
    row_number() over (partition by participant_id, session_id order by video_index)
      - row_number() over (partition by participant_id, session_id, early_skip order by video_index) as grp
  from v
),
runs as (
  -- 連続して early_skip = true となった区間の長さ
  select participant_id, session_id, grp, count(*) as run_len
  from ordered
  where early_skip
  group by participant_id, session_id, grp
),
max_run as (
  select participant_id, session_id, max(run_len) as max_consecutive_skip
  from runs
  group by participant_id, session_id
),
halves as (
  -- 前半 floor(n/2) 本と後半それぞれの早期スキップ率
  select
    participant_id,
    session_id,
    avg(case when rn <= floor(n / 2.0) then early_skip::int end) as first_rate,
    avg(case when rn >  floor(n / 2.0) then early_skip::int end) as second_rate
  from ordered
  group by participant_id, session_id
)
select
  o.participant_id,
  o.session_id,
  count(*)                                            as total_videos,        -- 総視聴本数
  sum(o.watched_sec)                                  as total_view_sec,      -- 総視聴時間（秒）
  avg(o.watched_sec)                                  as mean_view_sec,       -- 平均視聴時間（秒）
  avg(o.completed::int)                               as completion_rate,     -- 視聴完了率
  avg(o.early_skip::int)                              as early_skip_rate,     -- 早期スキップ率
  case
    when extract(epoch from (max(o.last_time) - min(o.first_time))) > 0
    then (count(*) - 1)
         / (extract(epoch from (max(o.last_time) - min(o.first_time))) / 60.0)
  end                                                 as switch_per_min,      -- 切り替え頻度（本/分）
  var_samp(o.watched_sec)                             as view_sec_var,        -- 視聴時間の分散
  coalesce(mr.max_consecutive_skip, 0)               as max_consecutive_skip, -- 連続スキップ長
  (h.second_rate - h.first_rate)                     as late_skip_increase,  -- 後半スキップ増加率
  string_agg(o.video_title, ' | ' order by o.video_index) as watched_titles, -- 視聴タイトル
  string_agg(coalesce(o.video_category, ''), ' | ' order by o.video_index)
                                                       as watched_categories, -- 視聴カテゴリ
  count(distinct nullif(o.video_category, ''))         as unique_category_count
from ordered o
left join max_run mr on mr.participant_id = o.participant_id and mr.session_id = o.session_id
left join halves  h  on h.participant_id  = o.participant_id and h.session_id  = o.session_id
group by
  o.participant_id, o.session_id,
  mr.max_consecutive_skip, h.second_rate, h.first_rate;

-- ---- PostgREST のスキーマキャッシュを再読み込み（API反映のため） ------------
-- これが無いと、テーブル作成直後に
--   「Could not find the table 'public.experiment_sessions' in the schema cache」
-- が出ることがある。
notify pgrst, 'reload schema';
