-- 既存の実験データを削除せず、視聴時間条件の列を追加するマイグレーション。
-- Supabase Dashboard > SQL Editor で、本機能をデプロイする前に1回実行する。

alter table experiment_sessions
  add column if not exists viewing_duration_minutes integer,
  add column if not exists expires_at timestamptz;

alter table view_logs
  add column if not exists viewing_duration_minutes integer;

-- 既存行は条件が未記録なのでNULLのまま保持する。新規行の値だけを検証する。
alter table experiment_sessions
  drop constraint if exists experiment_sessions_viewing_duration_minutes_check;

alter table experiment_sessions
  add constraint experiment_sessions_viewing_duration_minutes_check
  check (
    viewing_duration_minutes is null
    or viewing_duration_minutes in (5, 10, 15, 20, 25, 30)
  );

alter table view_logs
  drop constraint if exists view_logs_viewing_duration_minutes_check;

alter table view_logs
  add constraint view_logs_viewing_duration_minutes_check
  check (
    viewing_duration_minutes is null
    or viewing_duration_minutes in (5, 10, 15, 20, 25, 30)
  );

notify pgrst, 'reload schema';
