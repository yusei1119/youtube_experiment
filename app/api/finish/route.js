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
      .select("id, expires_at, finished_at")
      .eq("id", body.session_id)
      .single();

    if (sessionError || !session) {
      return NextResponse.json(
        { error: "session が見つかりません。" },
        { status: 404 }
      );
    }

    if (session.finished_at) {
      return NextResponse.json({ ok: true, finished_at: session.finished_at });
    }

    const now = new Date();
    const expiresAt = new Date(session.expires_at);
    const finishedAt =
      Number.isFinite(expiresAt.getTime()) && now >= expiresAt ? expiresAt : now;

    const { error } = await supabase
      .from("experiment_sessions")
      .update({
        finished_at: finishedAt.toISOString(),
        updated_at: now.toISOString(),
      })
      .eq("id", body.session_id)
      .is("finished_at", null);

    if (error) throw error;

    return NextResponse.json({ ok: true, finished_at: finishedAt.toISOString() });
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "finish failed" },
      { status: 500 }
    );
  }
}
