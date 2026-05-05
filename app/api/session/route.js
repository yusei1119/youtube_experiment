import { NextResponse } from "next/server";
import { fetchPlaylistVideos } from "@/lib/youtube";
import { shuffleArray } from "@/lib/shuffle";
import { createSupabaseAdmin } from "@/lib/supabaseAdmin";

export async function POST(request) {
  try {
    const body = await request.json();
    const participantId = body.participant_id?.trim();

    if (!participantId) {
      return NextResponse.json(
        { error: "participant_id が必要です。" },
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
      playlist_id: process.env.YOUTUBE_PLAYLIST_ID,
      video_count: shuffledVideos.length,
      video_order: shuffledVideos,
      current_index: 0,
      started_at: new Date().toISOString(),
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
      playlist_id: session.playlist_id,
      video_count: session.video_count,
      video_order: session.video_order,
      current_index: session.current_index,
      started_at: session.started_at,
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