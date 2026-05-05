"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export default function WatchPage() {
  const [session, setSession] = useState(null);
  const [index, setIndex] = useState(0);
  const [playerReady, setPlayerReady] = useState(false);
  const [pageLoaded, setPageLoaded] = useState(false);

  const playerRef = useRef(null);
  const progressTimerRef = useRef(null);
  const quartilesSentRef = useRef(new Set());
  const maxTimeRef = useRef(0);
  const lastCurrentTimeRef = useRef(0);
  const focusedRef = useRef(true);
  const mountedRef = useRef(false);

  const currentVideo = useMemo(() => {
    if (!session || !session.video_order || session.video_order.length === 0) {
      return null;
    }
    return session.video_order[index] || null;
  }, [session, index]);

  useEffect(() => {
    mountedRef.current = true;

    const saved = localStorage.getItem("youtube_experiment_session");
    if (!saved) {
      window.location.href = "/";
      return;
    }

    try {
      const parsed = JSON.parse(saved);
      setSession(parsed);
      setIndex(parsed.current_index || 0);
      setPageLoaded(true);
    } catch (error) {
      console.error(error);
      window.location.href = "/";
    }

    return () => {
      mountedRef.current = false;
      stopProgressTracking();
      destroyPlayer();
    };
  }, []);

  useEffect(() => {
    function onFocus() {
      focusedRef.current = true;
    }

    function onBlur() {
      focusedRef.current = false;
    }

    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);

    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  useEffect(() => {
    async function handleBeforeUnload() {
      await sendLog("page_exit");
    }

    function beforeUnloadHandler() {
      sendLog("page_exit");
    }

    window.addEventListener("beforeunload", beforeUnloadHandler);
    return () => {
      window.removeEventListener("beforeunload", beforeUnloadHandler);
      handleBeforeUnload();
    };
  }, [session, index, currentVideo]);

  useEffect(() => {
    if (!pageLoaded || !session || !currentVideo) return;

    stopProgressTracking();
    destroyPlayer();

    quartilesSentRef.current = new Set();
    maxTimeRef.current = 0;
    lastCurrentTimeRef.current = 0;
    setPlayerReady(false);

    initializeYouTubePlayer(currentVideo.video_id);

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageLoaded, session, index]);

  function initializeYouTubePlayer(videoId) {
    if (window.YT && window.YT.Player) {
      createPlayer(videoId);
      return;
    }

    if (!document.getElementById("youtube-iframe-api-script")) {
      const tag = document.createElement("script");
      tag.id = "youtube-iframe-api-script";
      tag.src = "https://www.youtube.com/iframe_api";
      document.body.appendChild(tag);
    }

    window.onYouTubeIframeAPIReady = () => {
      createPlayer(videoId);
    };
  }

  function createPlayer(videoId) {
    if (!mountedRef.current) return;

    playerRef.current = new window.YT.Player("youtube-player", {
      width: "360",
      height: "640",
      videoId,
      playerVars: {
        autoplay: 0,
        controls: 1,
        rel: 0,
        modestbranding: 1,
        playsinline: 1,
      },
      events: {
        onReady: handlePlayerReady,
        onStateChange: handlePlayerStateChange,
      },
    });
  }

  function destroyPlayer() {
    if (playerRef.current && typeof playerRef.current.destroy === "function") {
      try {
        playerRef.current.destroy();
      } catch (error) {
        console.error(error);
      }
      playerRef.current = null;
    }
  }

  async function handlePlayerReady() {
    setPlayerReady(true);
    await sendLog("video_loaded");
  }

  async function handlePlayerStateChange(event) {
    const YT = window.YT;

    if (event.data === YT.PlayerState.PLAYING) {
      await sendLog("play");
      startProgressTracking();
    } else if (event.data === YT.PlayerState.PAUSED) {
      await sendLog("pause");
      stopProgressTracking();
    } else if (event.data === YT.PlayerState.ENDED) {
      await sendLog("ended");
      stopProgressTracking();
      await goNext();
    } else if (event.data === YT.PlayerState.BUFFERING) {
      await sendLog("buffering");
    }
  }

  function startProgressTracking() {
    if (progressTimerRef.current) return;

    progressTimerRef.current = setInterval(async () => {
      const player = playerRef.current;
      if (!player) return;

      const current = safeCall(() => player.getCurrentTime());
      const duration = safeCall(() => player.getDuration());

      if (current == null || duration == null || duration <= 0) return;

      if (current > maxTimeRef.current) {
        maxTimeRef.current = current;
      }

      if (
        lastCurrentTimeRef.current > 0 &&
        Math.abs(current - lastCurrentTimeRef.current) > 3
      ) {
        await sendLog("seek_detected", {
          current_time_sec: current,
          duration_sec: duration,
          max_time_sec: maxTimeRef.current,
        });
      }

      const progressRate = current / duration;

      if (progressRate >= 0.25 && !quartilesSentRef.current.has("25")) {
        quartilesSentRef.current.add("25");
        await sendLog("progress_25", {
          current_time_sec: current,
          duration_sec: duration,
          progress_rate: progressRate,
          max_time_sec: maxTimeRef.current,
        });
      }

      if (progressRate >= 0.5 && !quartilesSentRef.current.has("50")) {
        quartilesSentRef.current.add("50");
        await sendLog("progress_50", {
          current_time_sec: current,
          duration_sec: duration,
          progress_rate: progressRate,
          max_time_sec: maxTimeRef.current,
        });
      }

      if (progressRate >= 0.75 && !quartilesSentRef.current.has("75")) {
        quartilesSentRef.current.add("75");
        await sendLog("progress_75", {
          current_time_sec: current,
          duration_sec: duration,
          progress_rate: progressRate,
          max_time_sec: maxTimeRef.current,
        });
      }

      if (progressRate >= 0.95 && !quartilesSentRef.current.has("95")) {
        quartilesSentRef.current.add("95");
        await sendLog("progress_95", {
          current_time_sec: current,
          duration_sec: duration,
          progress_rate: progressRate,
          max_time_sec: maxTimeRef.current,
        });
      }

      await sendLog("progress", {
        current_time_sec: current,
        duration_sec: duration,
        progress_rate: progressRate,
        max_time_sec: maxTimeRef.current,
      });

      lastCurrentTimeRef.current = current;
    }, 1000);
  }

  function stopProgressTracking() {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }

  function safeCall(fn) {
    try {
      const value = fn();
      return typeof value === "undefined" ? null : value;
    } catch {
      return null;
    }
  }

  async function sendLog(eventType, extra = {}) {
    if (!session || !currentVideo) return;

    const player = playerRef.current;

    const currentTime = extra.current_time_sec ?? safeCall(() => player?.getCurrentTime());
    const duration = extra.duration_sec ?? safeCall(() => player?.getDuration());

    const payload = {
      session_id: session.session_id,
      participant_id: session.participant_id,
      video_id: currentVideo.video_id,
      video_title: currentVideo.title,
      video_index: index,
      event_type: eventType,

      current_time_sec: currentTime,
      duration_sec: duration,
      progress_rate:
        extra.progress_rate ??
        (currentTime != null && duration ? currentTime / duration : null),
      max_time_sec: extra.max_time_sec ?? maxTimeRef.current,

      playback_rate: safeCall(() => player?.getPlaybackRate()),
      muted: safeCall(() => player?.isMuted()),
      volume: safeCall(() => player?.getVolume()),

      visibility_state: document.visibilityState,
      window_focused: focusedRef.current,
      user_agent: navigator.userAgent,

      ...extra,
    };

    try {
      await fetch("/api/log", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      console.error("log send failed:", error);
    }
  }

  async function goNext() {
    const nextIndex = index + 1;

    if (nextIndex >= session.video_order.length) {
      await fetch("/api/finish", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: session.session_id,
        }),
      });

      alert("実験は終了しました。");
      localStorage.removeItem("youtube_experiment_session");
      window.location.href = "/";
      return;
    }

    const updatedSession = {
      ...session,
      current_index: nextIndex,
    };

    localStorage.setItem("youtube_experiment_session", JSON.stringify(updatedSession));
    setSession(updatedSession);
    setIndex(nextIndex);
  }

  async function skipVideo() {
    await sendLog("skip");
    stopProgressTracking();
    await goNext();
  }

  if (!session || !currentVideo) {
    return <main style={{ padding: 24 }}>読み込み中...</main>;
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#000",
        color: "#fff",
        display: "flex",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 14, opacity: 0.8 }}>
            参加者ID: {session.participant_id}
          </div>
          <div style={{ fontSize: 14, opacity: 0.8 }}>
            {index + 1} / {session.video_order.length}
          </div>
        </div>

        <h2 style={{ fontSize: 16, lineHeight: 1.5, marginBottom: 12 }}>
          {currentVideo.title}
        </h2>

        <div
          style={{
            width: "100%",
            aspectRatio: "9 / 16",
            background: "#111",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <div id="youtube-player" style={{ width: "100%", height: "100%" }} />
        </div>

        <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
          <button
            onClick={skipVideo}
            disabled={!playerReady}
            style={{
              flex: 1,
              padding: 14,
              borderRadius: 10,
              border: "none",
              fontSize: 16,
              cursor: "pointer",
            }}
          >
            次の動画へ
          </button>
        </div>
      </div>
    </main>
  );
}