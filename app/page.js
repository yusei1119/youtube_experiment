"use client";

import { useState } from "react";

export default function HomePage() {
  const [participantId, setParticipantId] = useState("");
  const [viewingDurationMinutes, setViewingDurationMinutes] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  function reviewExperiment() {
    const pid = participantId.trim();

    if (!pid) {
      alert("参加者IDを入力してください。");
      return;
    }

    if (!viewingDurationMinutes) {
      alert("視聴時間の条件を選択してください。");
      return;
    }

    setConfirming(true);
  }

  async function startExperiment() {
    const pid = participantId.trim();

    setLoading(true);

    try {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          participant_id: pid,
          viewing_duration_minutes: Number(viewingDurationMinutes),
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
        指定された参加者IDと視聴時間の条件を入力して開始してください
        <br />
        動画順は参加者ごとにシャッフルされ、視聴ログが保存されます
        <br />
        視聴時間が終了すると動画は自動的に停止します
      </p>

      <label htmlFor="participant-id" style={{ display: "block", marginTop: 24, fontWeight: 700 }}>
        参加者ID
      </label>
      <input
        id="participant-id"
        type="text"
        value={participantId}
        onChange={(e) => {
          setParticipantId(e.target.value);
          setConfirming(false);
        }}
        placeholder="例: A001"
        style={{
          width: "100%",
          padding: 12,
          fontSize: 18,
          marginTop: 8,
          marginBottom: 20,
          border: "1px solid #ccc",
          borderRadius: 8,
        }}
      />

      <label htmlFor="viewing-duration" style={{ display: "block", fontWeight: 700 }}>
        ショート動画の視聴時間
      </label>
      <select
        id="viewing-duration"
        value={viewingDurationMinutes}
        onChange={(event) => {
          setViewingDurationMinutes(event.target.value);
          setConfirming(false);
        }}
        style={{
          width: "100%",
          padding: 12,
          fontSize: 18,
          marginTop: 8,
          marginBottom: 24,
          border: "1px solid #ccc",
          borderRadius: 8,
          background: "#fff",
        }}
      >
        <option value="">選択してください</option>
        {[5, 10, 15, 20, 25, 30].map((minutes) => (
          <option key={minutes} value={minutes}>
            {minutes}分
          </option>
        ))}
      </select>

      <button
        onClick={reviewExperiment}
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
        実験開始
      </button>

      {confirming && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirmation-title"
          style={{
            position: "fixed",
            inset: 0,
            display: "grid",
            placeItems: "center",
            padding: 24,
            background: "rgba(0, 0, 0, 0.55)",
          }}
        >
          <section
            style={{
              width: "min(100%, 480px)",
              padding: 28,
              borderRadius: 12,
              background: "#fff",
              boxShadow: "0 24px 80px rgba(0, 0, 0, 0.3)",
            }}
          >
            <h2 id="confirmation-title" style={{ marginTop: 0 }}>
              入力内容を確認してください
            </h2>
            <dl style={{ margin: "24px 0", lineHeight: 1.8 }}>
              <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 12 }}>
                <dt>参加者ID</dt>
                <dd style={{ margin: 0, fontWeight: 800 }}>{participantId.trim()}</dd>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 12 }}>
                <dt>視聴時間の条件</dt>
                <dd style={{ margin: 0, fontWeight: 800 }}>{viewingDurationMinutes}分</dd>
              </div>
            </dl>
            <p>この内容で正しい場合のみ、実験を開始してください。</p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 24 }}>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={loading}
                style={{ padding: "11px 18px", fontSize: 16, borderRadius: 8 }}
              >
                入力を修正
              </button>
              <button
                type="button"
                onClick={startExperiment}
                disabled={loading}
                style={{
                  padding: "11px 18px",
                  fontSize: 16,
                  border: 0,
                  borderRadius: 8,
                  background: "#111",
                  color: "#fff",
                }}
              >
                {loading ? "開始準備中..." : "この内容で実験を開始"}
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
