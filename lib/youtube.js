export async function fetchPlaylistVideos() {
  const apiKey = process.env.YOUTUBE_API_KEY;
  const playlistId = process.env.YOUTUBE_PLAYLIST_ID;

  if (!apiKey || !playlistId) {
    throw new Error("YOUTUBE_API_KEY または YOUTUBE_PLAYLIST_ID が未設定です。");
  }

  let videos = [];
  let pageToken = "";

  do {
    const url = new URL("https://www.googleapis.com/youtube/v3/playlistItems");
    url.searchParams.set("part", "snippet,contentDetails");
    url.searchParams.set("playlistId", playlistId);
    url.searchParams.set("maxResults", "50");
    url.searchParams.set("key", apiKey);
    if (pageToken) {
      url.searchParams.set("pageToken", pageToken);
    }

    const res = await fetch(url.toString(), {
      cache: "no-store",
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`YouTube API error: ${text}`);
    }

    const data = await res.json();

    const pageVideos = (data.items || [])
      .map((item) => ({
        video_id: item?.contentDetails?.videoId,
        title: item?.snippet?.title || "",
        position: item?.snippet?.position ?? null,
        thumbnail: item?.snippet?.thumbnails?.medium?.url || "",
      }))
      .filter((v) => v.video_id);

    videos.push(...pageVideos);
    pageToken = data.nextPageToken || "";
  } while (pageToken);

  return videos;
}