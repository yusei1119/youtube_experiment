"use client";

import { useState } from "react";

export default function HomePage() {
  const [participantId, setParticipantId] = useState("");
  const [loading, setLoading] = useState(false);

  async function startExperiment() {
    const pid = participantId.trim();

    if (!pid) {
      alert("参加者IDを入力してください。");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          participant_id: pid,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "セッション作成に失敗しました。");
      }

      localStorage.setItem("youtube_experiment_session", JSON.stringify(data));
      window.location.href = "/watch";
    } catch (error) {
      alert(error.message);
      setLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: 640, margin: "80px auto", padding: 24 }}>
      <h1 style={{ fontSize: 32, marginBottom: 16 }}>ショート動画視聴実験</h1>

      <p style={{ lineHeight: 1.8 }}>
        指定された参加者IDを入力して開始してください
        <br />
        動画順は参加者ごとにシャッフルされ、視聴ログが保存されます
        <br />
        実験終了後はページをキャッシュしてください
      </p>

      <input
        type="text"
        value={participantId}
        onChange={(e) => setParticipantId(e.target.value)}
        placeholder="例: A001"
        style={{
          width: "100%",
          padding: 12,
          fontSize: 18,
          marginTop: 20,
          marginBottom: 16,
          border: "1px solid #ccc",
          borderRadius: 8,
        }}
      />

      <button
        onClick={startExperiment}
        disabled={loading}
        style={{
          padding: "12px 24px",
          fontSize: 18,
          borderRadius: 8,
          border: "none",
          background: "#111",
          color: "#fff",
          cursor: "pointer",
        }}
      >
        {loading ? "開始準備中..." : "実験開始"}
      </button>
    </main>
  );
}