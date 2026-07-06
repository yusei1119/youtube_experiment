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

  return enrichVideosWithCategories(videos, apiKey);
}

function chunkArray(items, size) {
  const chunks = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

async function fetchYouTubeJson(url) {
  const res = await fetch(url.toString(), {
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`YouTube API error: ${text}`);
  }

  return res.json();
}

async function enrichVideosWithCategories(videos, apiKey) {
  const videoIds = videos.map((video) => video.video_id).filter(Boolean);
  const categoryByVideoId = new Map();
  const categoryIds = new Set();

  for (const ids of chunkArray(videoIds, 50)) {
    const url = new URL("https://www.googleapis.com/youtube/v3/videos");
    url.searchParams.set("part", "snippet");
    url.searchParams.set("id", ids.join(","));
    url.searchParams.set("key", apiKey);

    const data = await fetchYouTubeJson(url);

    for (const item of data.items || []) {
      const categoryId = item?.snippet?.categoryId || "";
      if (!item?.id || !categoryId) continue;

      categoryByVideoId.set(item.id, categoryId);
      categoryIds.add(categoryId);
    }
  }

  const categoryTitleById = await fetchCategoryTitles([...categoryIds], apiKey);

  return videos.map((video) => {
    const categoryId = categoryByVideoId.get(video.video_id) || "";
    return {
      ...video,
      category_id: categoryId,
      category_title: categoryTitleById.get(categoryId) || "",
    };
  });
}

async function fetchCategoryTitles(categoryIds, apiKey) {
  const titleById = new Map();
  if (categoryIds.length === 0) return titleById;

  for (const ids of chunkArray(categoryIds, 50)) {
    const url = new URL("https://www.googleapis.com/youtube/v3/videoCategories");
    url.searchParams.set("part", "snippet");
    url.searchParams.set("id", ids.join(","));
    url.searchParams.set("key", apiKey);

    const data = await fetchYouTubeJson(url);

    for (const item of data.items || []) {
      if (item?.id) {
        titleById.set(item.id, item?.snippet?.title || "");
      }
    }
  }

  return titleById;
}
