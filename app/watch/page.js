"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./watch.module.css";

const PLAYBACK_PULSE_HIDE_DELAY_MS = 0;

export default function WatchPage() {
  const [session, setSession] = useState(null);
  const [index, setIndex] = useState(0);
  const [playerReady, setPlayerReady] = useState(false);
  const [pageLoaded, setPageLoaded] = useState(false);
  const [liked, setLiked] = useState(false);
  const [commentOpen, setCommentOpen] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [shareCopied, setShareCopied] = useState(false);
  const [playbackPulse, setPlaybackPulse] = useState(null);
  const [swipeOffset, setSwipeOffset] = useState(0);
  const [swipeTransition, setSwipeTransition] = useState("");
  const [playbackProgress, setPlaybackProgress] = useState({
    current: 0,
    duration: 0,
  });
  const [isMuted, setIsMuted] = useState(true);
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const [startingPlayback, setStartingPlayback] = useState(false);
  const [experimentEnded, setExperimentEnded] = useState(false);

  const playerRef = useRef(null);
  const progressTimerRef = useRef(null);
  const playbackTimerRef = useRef(null);
  const quartilesSentRef = useRef(new Set());
  const maxTimeRef = useRef(0);
  const lastCurrentTimeRef = useRef(0);
  const focusedRef = useRef(true);
  const mountedRef = useRef(false);
  const pointerStartRef = useRef(null);
  const wheelLockedRef = useRef(false);
  const playbackPulseTimerRef = useRef(null);
  const autoplayRetryTimerRef = useRef(null);
  const swipeAnimationTimerRef = useRef(null);
  const startNextVideoWithSoundRef = useRef(false);
  const audioUnlockedRef = useRef(false);
  const experimentTimerRef = useRef(null);
  const finishingRef = useRef(false);
  const viewingStartRequestRef = useRef(false);

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

    async function restoreSession() {
      try {
        const parsed = JSON.parse(saved);
        const response = await fetch(
          `/api/session?session_id=${encodeURIComponent(parsed.session_id)}`,
          { cache: "no-store" }
        );
        const status = await response.json();

        if (!response.ok) {
          throw new Error(status.error || "セッションの確認に失敗しました。");
        }

        if (!mountedRef.current) return;

        const restored = {
          ...parsed,
          ...status,
          current_index: status.current_index ?? parsed.current_index ?? 0,
        };
        localStorage.setItem("youtube_experiment_session", JSON.stringify(restored));
        setSession(restored);
        setIndex(restored.current_index);
        setExperimentEnded(status.expired);
        setPageLoaded(true);

        if (status.expired && !status.finished_at) {
          fetch("/api/finish", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: restored.session_id }),
            keepalive: true,
          }).catch((error) => console.error("finish send failed:", error));
        }
      } catch (error) {
        console.error(error);
        alert(error.message || "セッションの確認に失敗しました。");
        localStorage.removeItem("youtube_experiment_session");
        window.location.href = "/";
      }
    }

    restoreSession();

    return () => {
      mountedRef.current = false;
      stopProgressTracking();
      stopPlaybackTracking();
      clearPlaybackPulse();
      clearAutoplayRetry();
      clearSwipeAnimation();
      clearExperimentTimer();
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
    function beforeUnloadHandler() {
      if (!experimentEnded) sendLog("page_exit");
    }
  
    window.addEventListener("beforeunload", beforeUnloadHandler);
  
    return () => {
      window.removeEventListener("beforeunload", beforeUnloadHandler);
    };
  }, [session, index, currentVideo, experimentEnded]);

  useEffect(() => {
    if (!session || experimentEnded || !session.started_at || !session.expires_at) {
      return;
    }

    function checkTimeLimit() {
      const expiresAtMs = new Date(session.expires_at).getTime();
      if (!Number.isFinite(expiresAtMs) || Date.now() >= expiresAtMs) {
        finishExperiment("time_limit");
      }
    }

    const expiresAtMs = new Date(session.expires_at).getTime();
    const remainingMs = Number.isFinite(expiresAtMs)
      ? Math.max(0, expiresAtMs - Date.now())
      : 0;
    experimentTimerRef.current = window.setTimeout(checkTimeLimit, remainingMs);
    window.addEventListener("focus", checkTimeLimit);
    document.addEventListener("visibilitychange", checkTimeLimit);
    checkTimeLimit();

    return () => {
      clearExperimentTimer();
      window.removeEventListener("focus", checkTimeLimit);
      document.removeEventListener("visibilitychange", checkTimeLimit);
    };
    // finishExperiment intentionally uses the latest values from this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, experimentEnded]);

  useEffect(() => {
    if (!pageLoaded || !session || !currentVideo || experimentEnded) return;

    stopProgressTracking();
    stopPlaybackTracking();
    clearAutoplayRetry();
    clearSwipeAnimation();

    quartilesSentRef.current = new Set();
    maxTimeRef.current = 0;
    lastCurrentTimeRef.current = 0;

    queueMicrotask(() => {
      if (!mountedRef.current) return;
      setLiked(false);
      setCommentOpen(false);
      setCommentText("");
      setShareCopied(false);
      setPlaybackPulse(null);
      setSwipeOffset(0);
      setSwipeTransition("");
      setPlaybackProgress({ current: 0, duration: 0 });
    });

    if (playerRef.current && typeof playerRef.current.loadVideoById === "function") {
      loadNextVideo(currentVideo.video_id);
    } else {
      destroyPlayer();
      queueMicrotask(() => {
        if (!mountedRef.current) return;
        setPlayerReady(false);
      });
      initializeYouTubePlayer(currentVideo.video_id);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageLoaded, index, experimentEnded]);

  function loadNextVideo(videoId) {
    const player = playerRef.current;
    disableCaptions();
    if (audioUnlockedRef.current) {
      safeCall(() => player.unMute());
      safeCall(() => player.setVolume(100));
      setIsMuted(false);
    } else {
      safeCall(() => player.mute());
      setIsMuted(true);
    }
    safeCall(() => player.loadVideoById({ videoId, startSeconds: 0 }));
  }

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
        controls: 0,
        mute: 1,
        cc_load_policy: 0,
        iv_load_policy: 3,
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
    disableCaptions();
    startNextVideoWithSoundRef.current = false;
    if (session?.started_at && session?.expires_at) {
      attemptAutoplay();
      startPlaybackTracking();
      await sendLog("video_loaded");
      await sendLog("autoplay_attempt");
    }
  }

  async function toggleMute() {
    const player = playerRef.current;
    if (!player) return;
    const muted = safeCall(() => player.isMuted());
    if (muted) {
      safeCall(() => player.unMute());
      safeCall(() => player.setVolume(100));
      setIsMuted(false);
      await sendLog("unmute");
    } else {
      safeCall(() => player.mute());
      setIsMuted(true);
      await sendLog("mute");
    }
  }

  async function handlePlayerStateChange(event) {
    const YT = window.YT;

    if (event.data === YT.PlayerState.PLAYING) {
      if (!session?.started_at || !session?.expires_at) {
        if (!audioUnlockedRef.current) {
          safeCall(() => playerRef.current?.pauseVideo());
          return;
        }

        const timerStarted = await startViewingTimer();
        if (!timerStarted) return;
      }

      setStartingPlayback(false);
      clearAutoplayRetry();
      disableCaptions();
      setPlayerReady(true);
      await sendLog("play");
      startProgressTracking();
      startPlaybackTracking();
    } else if (event.data === YT.PlayerState.PAUSED) {
      await sendLog("pause");
      stopProgressTracking();
    } else if (event.data === YT.PlayerState.ENDED) {
      await sendLog("ended");
      stopProgressTracking();
      await loopCurrentVideo();
    } else if (event.data === YT.PlayerState.BUFFERING) {
      await sendLog("buffering");
    }
  }

  function disableCaptions() {
    safeCall(() => playerRef.current?.unloadModule("captions"));
    safeCall(() => playerRef.current?.unloadModule("cc"));
    safeCall(() => playerRef.current?.setOption("captions", "track", {}));
  }

  async function loopCurrentVideo() {
    quartilesSentRef.current = new Set();
    maxTimeRef.current = 0;
    lastCurrentTimeRef.current = 0;
    setPlaybackProgress((previous) => ({
      current: 0,
      duration: previous.duration,
    }));
    safeCall(() => playerRef.current?.seekTo(0, true));
    disableCaptions();
    if (audioUnlockedRef.current) {
      safeCall(() => playerRef.current?.unMute());
      safeCall(() => playerRef.current?.setVolume(100));
      setIsMuted(false);
    }
    safeCall(() => playerRef.current?.playVideo());
    await sendLog("loop_replay", {
      current_time_sec: 0,
      max_time_sec: 0,
    });
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

  function startPlaybackTracking() {
    if (playbackTimerRef.current) return;

    playbackTimerRef.current = setInterval(() => {
      updatePlaybackProgress();
    }, 250);
    updatePlaybackProgress();
  }

  function stopPlaybackTracking() {
    if (playbackTimerRef.current) {
      clearInterval(playbackTimerRef.current);
      playbackTimerRef.current = null;
    }
  }

  function clearPlaybackPulse() {
    if (playbackPulseTimerRef.current) {
      clearTimeout(playbackPulseTimerRef.current);
      playbackPulseTimerRef.current = null;
    }
  }

  function clearAutoplayRetry() {
    if (autoplayRetryTimerRef.current) {
      clearTimeout(autoplayRetryTimerRef.current);
      autoplayRetryTimerRef.current = null;
    }
  }

  function clearSwipeAnimation() {
    if (swipeAnimationTimerRef.current) {
      clearTimeout(swipeAnimationTimerRef.current);
      swipeAnimationTimerRef.current = null;
    }
  }

  function clearExperimentTimer() {
    if (experimentTimerRef.current) {
      clearTimeout(experimentTimerRef.current);
      experimentTimerRef.current = null;
    }
  }

  function resetSwipePosition() {
    setSwipeTransition("transform 360ms cubic-bezier(0.18, 0.9, 0.24, 1)");
    setSwipeOffset(0);
  }

  function getSwipeDistance() {
    const shortHeight = document.querySelector(`.${styles.short}`)?.clientHeight;
    return (shortHeight || window.innerHeight || 720) + 40;
  }

  async function pageToVideo(direction, source = "swipe") {
    const isNext = direction === "next";
    const nextIndex = isNext ? index + 1 : index - 1;

    if (nextIndex >= session.video_order.length) {
      setSwipeTransition("transform 220ms cubic-bezier(0.2, 0.86, 0.34, 1)");
      setSwipeOffset(-getSwipeDistance());
      const logPromise = sendLog(source === "swipe" ? "swipe_next_finish" : "next_finish");
      stopProgressTracking();
      swipeAnimationTimerRef.current = window.setTimeout(async () => {
        swipeAnimationTimerRef.current = null;
        await logPromise;
        await finishExperiment();
      }, 220);
      return;
    }

    if (nextIndex < 0) {
      await sendLog(source === "swipe" ? "swipe_previous_blocked" : "previous_blocked");
      resetSwipePosition();
      return;
    }

    setSwipeTransition("transform 240ms cubic-bezier(0.16, 1, 0.3, 1)");
    setSwipeOffset(isNext ? -getSwipeDistance() : getSwipeDistance());

    const logPromise = sendLog(
      source === "swipe"
        ? isNext
          ? "swipe_next"
          : "swipe_previous"
        : isNext
          ? "next"
          : "previous"
    );
    stopProgressTracking();
    startNextVideoWithSoundRef.current = true;

    swipeAnimationTimerRef.current = window.setTimeout(() => {
      swipeAnimationTimerRef.current = null;
      setSwipeTransition("");
      setSwipeOffset(0);
      updateVideoIndex(nextIndex);
    }, 240);
    await logPromise;
  }

  function attemptAutoplay() {
    clearAutoplayRetry();
    disableCaptions();

    if (audioUnlockedRef.current) {
      safeCall(() => playerRef.current?.unMute());
      safeCall(() => playerRef.current?.setVolume(100));
      setIsMuted(false);
    } else {
      safeCall(() => playerRef.current?.mute());
      setIsMuted(true);
    }
    safeCall(() => playerRef.current?.playVideo());

    autoplayRetryTimerRef.current = window.setTimeout(() => {
      const YT = window.YT;
      const playerState = getPlayerState();
      if (playerState !== YT?.PlayerState?.PLAYING) {
        disableCaptions();
        if (!audioUnlockedRef.current) {
          safeCall(() => playerRef.current?.mute());
        }
        safeCall(() => playerRef.current?.playVideo());
      }
      autoplayRetryTimerRef.current = null;
    }, 700);
  }

  async function unlockAudio() {
    if (startingPlayback) return;
    setStartingPlayback(true);
    audioUnlockedRef.current = true;
    setAudioUnlocked(true);
    safeCall(() => playerRef.current?.unMute());
    safeCall(() => playerRef.current?.setVolume(100));
    safeCall(() => playerRef.current?.playVideo());
    setIsMuted(false);
  }

  async function startViewingTimer() {
    if (viewingStartRequestRef.current) return false;
    viewingStartRequestRef.current = true;

    try {
      const response = await fetch("/api/session", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "動画視聴の開始に失敗しました。");
      }

      const activeSession = { ...session, ...data };
      localStorage.setItem(
        "youtube_experiment_session",
        JSON.stringify(activeSession)
      );
      setSession(activeSession);
      setStartingPlayback(false);
      await sendLog("viewing_started", {
        viewing_started_at: activeSession.started_at,
      });
      return true;
    } catch (error) {
      console.error(error);
      safeCall(() => playerRef.current?.pauseVideo());
      audioUnlockedRef.current = false;
      setAudioUnlocked(false);
      setStartingPlayback(false);
      alert(error.message || "動画視聴の開始に失敗しました。");
      return false;
    } finally {
      viewingStartRequestRef.current = false;
    }
  }

  function flashPlaybackPulse(nextPulse) {
    clearPlaybackPulse();
    setPlaybackPulse(nextPulse);
    playbackPulseTimerRef.current = window.setTimeout(() => {
      setPlaybackPulse(null);
      playbackPulseTimerRef.current = null;
    }, PLAYBACK_PULSE_HIDE_DELAY_MS);
  }

  function updatePlaybackProgress() {
    const player = playerRef.current;
    if (!player) return;

    const current = safeCall(() => player.getCurrentTime());
    const duration = safeCall(() => player.getDuration());

    if (current == null || duration == null || duration <= 0) return;

    setPlaybackProgress({
      current,
      duration,
    });
  }

  function getPlayerState() {
    return safeCall(() => playerRef.current?.getPlayerState());
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

  function updateVideoIndex(nextIndex) {
    const updatedSession = {
      ...session,
      current_index: nextIndex,
    };

    localStorage.setItem("youtube_experiment_session", JSON.stringify(updatedSession));
    setSession(updatedSession);
    setIndex(nextIndex);
  }

  async function finishExperiment(reason = "completed") {
    if (!session || finishingRef.current || experimentEnded) return;

    finishingRef.current = true;
    clearExperimentTimer();
    stopProgressTracking();
    stopPlaybackTracking();
    clearAutoplayRetry();
    clearSwipeAnimation();
    safeCall(() => playerRef.current?.pauseVideo());
    destroyPlayer();
    setPlayerReady(false);
    setCommentOpen(false);
    setExperimentEnded(true);

    const finishedSession = {
      ...session,
      finished_at:
        reason === "time_limit"
          ? session.expires_at || new Date().toISOString()
          : new Date().toISOString(),
      finish_reason: reason,
    };
    localStorage.setItem(
      "youtube_experiment_session",
      JSON.stringify(finishedSession)
    );
    setSession(finishedSession);

    try {
      const response = await fetch("/api/finish", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: session.session_id,
          reason,
        }),
        keepalive: true,
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || "終了時刻の保存に失敗しました。");
      }
    } catch (error) {
      console.error("finish send failed:", error);
    }
  }

  async function goNext(source = "button") {
    await pageToVideo("next", source);
  }

  async function goPrevious(source = "button") {
    await pageToVideo("previous", source);
  }

  async function skipVideo() {
    await sendLog("skip");
    stopProgressTracking();
    await goNext("button");
  }

  async function togglePlaybackByTap() {
    if (!playerReady || commentOpen) return;

    const playerState = getPlayerState();
    const YT = window.YT;
    const currentlyPlaying = playerState === YT?.PlayerState?.PLAYING;

    if (currentlyPlaying) {
      safeCall(() => playerRef.current?.pauseVideo());
      flashPlaybackPulse("pause");
      await sendLog("tap_pause");
    } else {
      disableCaptions();
      if (audioUnlockedRef.current) {
        safeCall(() => playerRef.current?.unMute());
        safeCall(() => playerRef.current?.setVolume(100));
        setIsMuted(false);
      }
      safeCall(() => playerRef.current?.playVideo());
      await sendLog("tap_play");
    }
  }

  function handlePointerDown(event) {
    if (commentOpen || !playerReady || swipeAnimationTimerRef.current) return;

    pointerStartRef.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      lastY: event.clientY,
      lastTime: Date.now(),
      time: Date.now(),
    };
    setSwipeTransition("");
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event) {
    const start = pointerStartRef.current;

    if (!start || start.id !== event.pointerId || commentOpen || !playerReady) return;

    const deltaX = event.clientX - start.x;
    const deltaY = event.clientY - start.y;

    if (Math.abs(deltaY) < 8 || Math.abs(deltaY) < Math.abs(deltaX) * 1.15) return;

    const isBlockedAtTop = deltaY > 0 && index === 0;
    const isBlockedAtEnd = deltaY < 0 && index >= session.video_order.length - 1;
    const resistance = isBlockedAtTop || isBlockedAtEnd ? 0.24 : 0.82;
    const nextOffset = deltaY * resistance;

    start.lastY = event.clientY;
    start.lastTime = Date.now();
    setSwipeOffset(nextOffset);
  }

  async function handlePointerUp(event) {
    const start = pointerStartRef.current;
    pointerStartRef.current = null;

    if (!start || start.id !== event.pointerId || commentOpen || !playerReady) return;

    const deltaX = event.clientX - start.x;
    const deltaY = event.clientY - start.y;
    const elapsed = Date.now() - start.time;
    const velocityY = (event.clientY - start.lastY) / Math.max(1, Date.now() - start.lastTime);
    const isTap = Math.abs(deltaX) < 12 && Math.abs(deltaY) < 12 && elapsed < 350;
    const isVerticalSwipe =
      (Math.abs(deltaY) > 72 || Math.abs(velocityY) > 0.75) &&
      Math.abs(deltaY) > Math.abs(deltaX) * 1.15;

    if (isTap) {
      resetSwipePosition();
      await togglePlaybackByTap();
      return;
    }

    if (!isVerticalSwipe || elapsed > 900) {
      resetSwipePosition();
      return;
    }

    if (deltaY < 0) {
      await goNext("swipe");
    } else {
      await goPrevious("swipe");
    }
  }

  async function seekToProgress(event) {
    const duration = playbackProgress.duration;
    const nextCurrent = (Number(event.target.value) / 1000) * duration;

    if (!duration || !Number.isFinite(nextCurrent)) return;

    safeCall(() => playerRef.current?.seekTo(nextCurrent, true));
    setPlaybackProgress({
      current: nextCurrent,
      duration,
    });
    lastCurrentTimeRef.current = nextCurrent;

    await sendLog("scrub_seek", {
      current_time_sec: nextCurrent,
      duration_sec: duration,
      progress_rate: nextCurrent / duration,
      max_time_sec: maxTimeRef.current,
    });
  }

  async function handleWheel(event) {
    if (commentOpen || !playerReady || wheelLockedRef.current) return;
    if (Math.abs(event.deltaY) < 90 || Math.abs(event.deltaY) < Math.abs(event.deltaX) * 1.5) {
      return;
    }

    wheelLockedRef.current = true;
    window.setTimeout(() => {
      wheelLockedRef.current = false;
    }, 700);

    if (event.deltaY > 0) {
      await goNext("swipe");
    } else {
      await goPrevious("swipe");
    }
  }

  async function toggleLike() {
    const nextLiked = !liked;
    setLiked(nextLiked);
    await sendLog(nextLiked ? "like" : "unlike");
  }

  async function toggleComments() {
    const nextOpen = !commentOpen;
    setCommentOpen(nextOpen);
    await sendLog(nextOpen ? "comments_open" : "comments_close");
  }

  async function submitComment(event) {
    event.preventDefault();

    const trimmed = commentText.trim();
    if (!trimmed) return;

    await sendLog("comment_submit", {
      comment_length: trimmed.length,
    });
    setCommentText("");
    setCommentOpen(false);
  }

  async function shareVideo() {
    const url = `https://www.youtube.com/watch?v=${currentVideo.video_id}`;

    try {
      if (navigator.share) {
        await navigator.share({
          title: currentVideo.title,
          url,
        });
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(url);
      }
      setShareCopied(true);
      window.setTimeout(() => setShareCopied(false), 1600);
      await sendLog("share");
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.error(error);
      }
    }
  }

  if (experimentEnded) {
    return (
      <main className={styles.endedPage}>
        <section className={styles.endedCard} aria-labelledby="experiment-ended-title">
          <div className={styles.endedIcon} aria-hidden="true">✓</div>
          <h1 id="experiment-ended-title">ショート動画の視聴条件は終了です。</h1>
          <p>このウインドウを閉じてください。</p>
          <p>メールに従って、次のタスクに移行してください。</p>
        </section>
      </main>
    );
  }

  if (!session || !currentVideo) {
    return <main className={styles.loading}>loading...</main>;
  }

  const progressValue = playbackProgress.duration
    ? Math.min(1000, Math.max(0, (playbackProgress.current / playbackProgress.duration) * 1000))
    : 0;

  return (
    <main className={styles.page}>
      <section className={styles.viewer} aria-label="YouTube Shorts style viewer">
        <div className={styles.short}>
          <div
            className={styles.swipeSurface}
            style={{
              transform: `translate3d(0, ${swipeOffset}px, 0)`,
              transition: swipeTransition,
            }}
          >
            <div className={styles.playerFrame}>
              <div id="youtube-player" className={styles.player} />
            </div>

            <div className={styles.bottomGradient} aria-hidden="true" />

            <div
              className={styles.gestureLayer}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={() => {
                pointerStartRef.current = null;
                resetSwipePosition();
              }}
              onWheel={handleWheel}
              aria-hidden="true"
            />
            {playbackPulse && (
              <div className={styles.playbackPulse} aria-hidden="true">
                {playbackPulse === "play" ? "▶" : "⏸"}
              </div>
            )}

            {!audioUnlocked && playerReady && (
              <button
                className={styles.startOverlay}
                onClick={unlockAudio}
                type="button"
                disabled={startingPlayback}
                aria-label="タップして音声付きで開始"
              >
                <span className={styles.startIcon} aria-hidden="true">▶</span>
                <span className={styles.startText}>
                  {startingPlayback ? "開始準備中..." : "タップして開始"}
                </span>
                <span className={styles.startSub}>
                  このタップから視聴時間を計測します
                </span>
              </button>
            )}

            <div className={styles.progressControl}>
              <input
                className={styles.progressRange}
                type="range"
                min="0"
                max="1000"
                step="1"
                value={progressValue}
                onChange={seekToProgress}
                disabled={!playerReady || !playbackProgress.duration}
                aria-label="動画の再生位置"
                style={{
                  "--progress": `${progressValue / 10}%`,
                }}
              />
            </div>

            <div className={styles.actionRail} aria-label="動画アクション">
              <button
                className={`${styles.actionButton} ${liked ? styles.activeAction : ""}`}
                onClick={toggleLike}
                type="button"
                aria-pressed={liked}
                title="いいね"
              >
                <span className={`${styles.actionIcon} ${styles.likeIcon}`} aria-hidden="true" />
                <span className={styles.actionLabel}>1,120</span>
              </button>

              <button
                className={styles.actionButton}
                onClick={toggleComments}
                type="button"
                aria-expanded={commentOpen}
                title="コメント"
              >
                <span className={`${styles.actionIcon} ${styles.commentIcon}`} aria-hidden="true" />
                <span className={styles.actionLabel}>2,293</span>
              </button>

              <button
                className={styles.actionButton}
                onClick={shareVideo}
                type="button"
                title="共有"
              >
                <span className={`${styles.actionIcon} ${styles.shareIcon}`} aria-hidden="true" />
                <span className={styles.actionLabel}>{shareCopied ? "コピー済み" : "共有"}</span>
              </button>

              <button
                className={styles.actionButton}
                onClick={() => goPrevious("button")}
                disabled={!playerReady || index === 0}
                type="button"
                title="前の動画へ"
              >
                <span className={`${styles.actionIcon} ${styles.prevGlyphIcon}`} aria-hidden="true">
                  ↑
                </span>
                <span className={styles.actionLabel}>前へ</span>
              </button>

              <button
                className={styles.actionButton}
                onClick={skipVideo}
                disabled={!playerReady}
                type="button"
                title="次の動画へ"
              >
                <span className={`${styles.actionIcon} ${styles.nextGlyphIcon}`} aria-hidden="true">
                  ↓
                </span>
                <span className={styles.actionLabel}>次へ</span>
              </button>
            </div>

            <div className={styles.videoInfo}>
              <div className={styles.channelRow}>
                <div className={styles.avatar}>YT</div>
                <div className={styles.channelName}>@YouTube視聴実験</div>
                <button className={styles.subscribeButton} type="button">
                  チャンネル登録
                </button>
              </div>
              <h1 className={styles.title}>{currentVideo.title}</h1>
            </div>

            {commentOpen && (
              <form className={styles.commentSheet} onSubmit={submitComment}>
                <div className={styles.commentHeader}>
                  <strong>コメント</strong>
                  <button type="button" onClick={toggleComments} className={styles.closeButton}>
                    ×
                  </button>
                </div>
                <textarea
                  value={commentText}
                  onChange={(event) => setCommentText(event.target.value)}
                  className={styles.commentInput}
                  placeholder="コメントを追加"
                  rows={3}
                />
                <button className={styles.commentSubmit} type="submit" disabled={!commentText.trim()}>
                  送信
                </button>
              </form>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
