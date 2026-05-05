import { NextResponse } from "next/server";
import { createSupabaseAdmin } from "@/lib/supabaseAdmin";

export async function POST(request) {
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
      .select("*")
      .eq("id", body.session_id)
      .single();

    if (sessionError || !session) {
      return NextResponse.json(
        { error: "session が見つかりません。" },
        { status: 404 }
      );
    }

    const log = {
      id: crypto.randomUUID(),
      server_time: new Date().toISOString(),

      participant_id: session.participant_id,
      session_id: session.id,
      playlist_id: session.playlist_id,

      video_id: body.video_id ?? null,
      video_title: body.video_title ?? "",
      video_index: body.video_index ?? null,
      event_type: body.event_type ?? "unknown",

      current_time_sec: body.current_time_sec ?? null,
      duration_sec: body.duration_sec ?? null,
      progress_rate: body.progress_rate ?? null,
      max_time_sec: body.max_time_sec ?? null,

      playback_rate: body.playback_rate ?? null,
      muted: body.muted ?? null,
      volume: body.volume ?? null,

      visibility_state: body.visibility_state ?? null,
      window_focused: body.window_focused ?? null,
      user_agent: body.user_agent ?? "",
    };

    const { error: insertError } = await supabase
      .from("view_logs")
      .insert(log);

    if (insertError) throw insertError;

    if (typeof body.video_index === "number") {
      await supabase
        .from("experiment_sessions")
        .update({
          current_index: body.video_index,
          updated_at: new Date().toISOString(),
        })
        .eq("id", body.session_id);
    }

    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "log save failed" },
      { status: 500 }
    );
  }
}