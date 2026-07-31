import { NextResponse } from "next/server";
import { fetchPlaylistVideos } from "@/lib/youtube";
import { shuffleArray } from "@/lib/shuffle";
import { createSupabaseAdmin } from "@/lib/supabaseAdmin";

const ALLOWED_VIEWING_DURATIONS = new Set([5, 10, 15, 20, 25, 30]);

function sessionStatus(session) {
  const timerStarted = Boolean(session.started_at && session.expires_at);
  const expiresAtMs = timerStarted
    ? new Date(session.expires_at).getTime()
    : Number.NaN;

  return {
    session_id: session.id,
    participant_id: session.participant_id,
    current_index: session.current_index,
    viewing_duration_minutes: session.viewing_duration_minutes,
    started_at: session.started_at,
    expires_at: session.expires_at,
    finished_at: session.finished_at,
    updated_at: session.updated_at,
    timer_started: timerStarted,
    expired:
      Boolean(session.finished_at) ||
      (timerStarted &&
        (!Number.isFinite(expiresAtMs) || Date.now() >= expiresAtMs)),
  };
}

export async function GET(request) {
  try {
    const sessionId = new URL(request.url).searchParams.get("session_id");

    if (!sessionId) {
      return NextResponse.json(
        { error: "session_id が必要です。" },
        { status: 400 }
      );
    }

    const supabase = createSupabaseAdmin();
    const { data: session, error } = await supabase
      .from("experiment_sessions")
      .select(
        "id, participant_id, current_index, viewing_duration_minutes, started_at, expires_at, finished_at, updated_at"
      )
      .eq("id", sessionId)
      .single();

    if (error || !session) {
      return NextResponse.json(
        { error: "session が見つかりません。" },
        { status: 404 }
      );
    }

    return NextResponse.json(sessionStatus(session));
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "session status failed" },
      { status: 500 }
    );
  }
}

export async function PATCH(request) {
  try {
    const body = await request.json();
    if (!body.session_id) {
      return NextResponse.json(
        { error: "session_id が必要です。" },
        { status: 400 }
      );
    }

    const supabase = createSupabaseAdmin();
    const { data: session, error: sessionError } = await supabase
      .from("experiment_sessions")
      .select(
        "id, participant_id, current_index, viewing_duration_minutes, started_at, expires_at, finished_at, updated_at"
      )
      .eq("id", body.session_id)
      .single();

    if (sessionError || !session) {
      return NextResponse.json(
        { error: "session が見つかりません。" },
        { status: 404 }
      );
    }

    if (session.finished_at) {
      return NextResponse.json(
        { error: "この視聴セッションは終了しています。" },
        { status: 410 }
      );
    }

    if (session.started_at && session.expires_at) {
      return NextResponse.json(sessionStatus(session));
    }

    const startedAt = new Date();
    const expiresAt = new Date(
      startedAt.getTime() + session.viewing_duration_minutes * 60 * 1000
    );
    const { data: startedSession, error: updateError } = await supabase
      .from("experiment_sessions")
      .update({
        started_at: startedAt.toISOString(),
        expires_at: expiresAt.toISOString(),
        updated_at: startedAt.toISOString(),
      })
      .eq("id", session.id)
      .is("started_at", null)
      .select(
        "id, participant_id, current_index, viewing_duration_minutes, started_at, expires_at, finished_at, updated_at"
      )
      .maybeSingle();

    if (updateError) throw updateError;

    if (startedSession) {
      return NextResponse.json(sessionStatus(startedSession));
    }

    const { data: concurrentSession, error: concurrentError } = await supabase
      .from("experiment_sessions")
      .select(
        "id, participant_id, current_index, viewing_duration_minutes, started_at, expires_at, finished_at, updated_at"
      )
      .eq("id", session.id)
      .single();

    if (concurrentError || !concurrentSession) {
      throw concurrentError || new Error("視聴開始時刻の保存に失敗しました。");
    }

    return NextResponse.json(sessionStatus(concurrentSession));
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "viewing start failed" },
      { status: 500 }
    );
  }
}

export async function POST(request) {
  try {
    const body = await request.json();
    const participantId = body.participant_id?.trim();
    const viewingDurationMinutes = Number(body.viewing_duration_minutes);

    if (!participantId) {
      return NextResponse.json(
        { error: "participant_id が必要です。" },
        { status: 400 }
      );
    }

    if (!ALLOWED_VIEWING_DURATIONS.has(viewingDurationMinutes)) {
      return NextResponse.json(
        { error: "視聴時間は5分から30分まで、5分刻みで選択してください。" },
        { status: 400 }
      );
    }

    const videos = await fetchPlaylistVideos();

    if (!videos || videos.length === 0) {
      return NextResponse.json(
        { error: "再生リストから動画を取得できませんでした。" },
        { status: 500 }
      );
    }

    const shuffledVideos = shuffleArray(videos);

    const session = {
      id: crypto.randomUUID(),
      participant_id: participantId,
      viewing_duration_minutes: viewingDurationMinutes,
      playlist_id: process.env.YOUTUBE_PLAYLIST_ID,
      video_count: shuffledVideos.length,
      video_order: shuffledVideos,
      current_index: 0,
      started_at: null,
      expires_at: null,
      finished_at: null,
      updated_at: new Date().toISOString(),
    };

    const supabase = createSupabaseAdmin();

    const { error } = await supabase
      .from("experiment_sessions")
      .insert(session);

    if (error) throw error;

    return NextResponse.json({
      session_id: session.id,
      participant_id: session.participant_id,
      viewing_duration_minutes: session.viewing_duration_minutes,
      playlist_id: session.playlist_id,
      video_count: session.video_count,
      video_order: session.video_order,
      current_index: session.current_index,
      started_at: session.started_at,
      expires_at: session.expires_at,
      finished_at: session.finished_at,
      updated_at: session.updated_at,
    });
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "session create failed" },
      { status: 500 }
    );
  }
}
