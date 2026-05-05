import { NextResponse } from "next/server";
import { fetchPlaylistVideos } from "@/lib/youtube";

export async function GET() {
  try {
    const videos = await fetchPlaylistVideos();
    return NextResponse.json({
      count: videos.length,
      videos,
    });
  } catch (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message || "playlist fetch failed" },
      { status: 500 }
    );
  }
}