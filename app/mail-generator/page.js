"use client";

import { useEffect, useMemo, useState } from "react";
import styles from "./page.module.css";

const STORAGE_KEY = "experiment-mail-generator-urls-v1";

const CONDITIONS = {
  short: {
    name: "ショート動画",
    label: "SHORT VIDEO",
    color: "blue",
  },
  meditation: {
    name: "瞑想動画",
    label: "MEDITATION",
    color: "green",
  },
  daily: {
    name: "日常動画",
    label: "DAILY VIDEO",
    color: "orange",
  },
};

const DEFAULT_URLS = {
  trailers: Array(8).fill(""),
  dailyVideos: Array(10).fill(""),
  comprehensionTests: Array(10).fill(""),
};

const FIXED_URLS = {
  short: "https://youtube-experiment.vercel.app/",
  meditation:
    "https://drive.google.com/file/d/1JbmShwdUFkXOnLbwJp-MvXP0iJGA8z6O/view?usp=sharing",
  finalSurvey: "https://forms.gle/C21LeEya8L2UBUcA7",
};

function numberedOptions(count) {
  return Array.from({ length: count }, (_, index) => index + 1);
}

function selectedUrl(urls, key, number, label) {
  return urls[key][number - 1]?.trim() || `【URL未登録：${label} ${number}】`;
}

function buildConditionText(condition, selections, urls) {
  const trailerUrl = selectedUrl(
    urls,
    "trailers",
    selections.trailers[condition],
    "映画予告",
  );

  if (condition === "daily") {
    const dailyUrl = selectedUrl(
      urls,
      "dailyVideos",
      selections.dailyVideo,
      "日常動画",
    );
    const testUrl = selectedUrl(
      urls,
      "comprehensionTests",
      selections.comprehensionTest,
      "理解度テスト",
    );

    return `[1] 日常動画URL:\n${dailyUrl}\n↓\n\n[2] 理解度テストURL:\n${testUrl}\n↓\n\n[3] 日常動画後のアンケート:\n添付ファイル参照：NASA_task_90.html\n↓\n\n[4] 2分間の映画予告映像URL:\n${trailerUrl}\n↓\n\n[5] 日常動画後の記述タスク:\n添付ファイル参照：Writing_task_90.html`;
  }

  const isShort = condition === "short";
  const videoLabel = isShort ? "ショート動画**(スマホ)**" : "瞑想動画";
  const videoUrl = isShort ? FIXED_URLS.short : FIXED_URLS.meditation;
  const taskLabel = isShort ? "ショート動画" : "瞑想動画";

  return `[1] ${videoLabel}URL:\n${videoUrl}\n↓\n\n[2] ${taskLabel}後のアンケート:\n添付ファイル参照：NASA_task_90.html\n↓\n\n[3] 2分間の映画予告映像URL:\n${trailerUrl}\n↓\n\n[4] ${taskLabel}後の記述タスク:\n添付ファイル参照：Writing_task_90.html`;
}

function buildMail(participantId, order, selections, urls) {
  const blocks = order.map((condition, index) => {
    const heading = `実験${index + 1}（${CONDITIONS[condition].name}条件）`;
    const breakText = index < order.length - 1 ? "\n\n休憩（3分）" : "";
    return `${heading}\n\n${"*".repeat(24)}\n${buildConditionText(condition, selections, urls)}${breakText}`;
  });

  return `実験参加者ID:\n${participantId.trim() || "XX"}\n\n${blocks.join("\n\n")}\n\n${"*".repeat(24)}\n[6] 実験後のアンケートURL:\n${FIXED_URLS.finalSurvey}`;
}

function SelectField({ label, value, count, onChange }) {
  return (
    <label className={styles.selectField}>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {numberedOptions(count).map((number) => (
          <option key={number} value={number}>
            {number}
          </option>
        ))}
      </select>
    </label>
  );
}

function UrlGroup({ title, description, urlKey, count, urls, onUrlChange }) {
  return (
    <div className={styles.urlGroup}>
      <div className={styles.urlGroupHeading}>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <div className={styles.urlGrid}>
        {numberedOptions(count).map((number) => (
          <label key={number} className={styles.urlField}>
            <span>{String(number).padStart(2, "0")}</span>
            <input
              type="url"
              value={urls[urlKey][number - 1]}
              onChange={(event) => onUrlChange(urlKey, number - 1, event.target.value)}
              placeholder="https://"
              aria-label={`${title} ${number}のURL`}
            />
          </label>
        ))}
      </div>
    </div>
  );
}

export default function MailGeneratorPage() {
  const [participantId, setParticipantId] = useState("");
  const [order, setOrder] = useState(["short", "meditation", "daily"]);
  const [selections, setSelections] = useState({
    trailers: { short: 1, meditation: 2, daily: 3 },
    dailyVideo: 1,
    comprehensionTest: 1,
  });
  const [urls, setUrls] = useState(DEFAULT_URLS);
  const [showUrlSettings, setShowUrlSettings] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(STORAGE_KEY);
        if (saved) setUrls({ ...DEFAULT_URLS, ...JSON.parse(saved) });
      } catch {
        // 壊れた保存値は無視し、空の設定で開始する。
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  const mailText = useMemo(
    () => buildMail(participantId, order, selections, urls),
    [participantId, order, selections, urls],
  );

  const missingUrlCount = useMemo(() => {
    const selected = [
      urls.trailers[selections.trailers.short - 1],
      urls.trailers[selections.trailers.meditation - 1],
      urls.trailers[selections.trailers.daily - 1],
      urls.dailyVideos[selections.dailyVideo - 1],
      urls.comprehensionTests[selections.comprehensionTest - 1],
    ];
    return selected.filter((url) => !url?.trim()).length;
  }, [selections, urls]);

  function moveCondition(index, direction) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= order.length) return;
    const next = [...order];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    setOrder(next);
  }

  function updateTrailer(condition, value) {
    setSelections((current) => ({
      ...current,
      trailers: { ...current.trailers, [condition]: value },
    }));
  }

  function updateUrl(key, index, value) {
    setUrls((current) => {
      const next = { ...current, [key]: [...current[key]] };
      next[key][index] = value;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }

  async function copyMail() {
    try {
      await navigator.clipboard.writeText(mailText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      alert("コピーできませんでした。プレビューから手動でコピーしてください。");
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>EXPERIMENT TOOLS / 01</p>
          <h1>参加案内メール<br />ジェネレーター</h1>
          <p className={styles.intro}>
            条件と素材を選ぶだけで、参加者ごとの実験手順を時系列に整えます。
          </p>
        </div>
        <div className={styles.heroMark} aria-hidden="true">
          <span>MAIL</span>
          <strong>01</strong>
        </div>
      </header>

      <div className={styles.workspace}>
        <section className={styles.controls} aria-label="メール内容の設定">
          <div className={styles.sectionHeading}>
            <span>01</span>
            <div>
              <h2>参加者</h2>
              <p>メールに記載するIDを入力</p>
            </div>
          </div>
          <label className={styles.participantField}>
            <span>PARTICIPANT ID</span>
            <input
              value={participantId}
              onChange={(event) => setParticipantId(event.target.value)}
              placeholder="例：P001"
              autoComplete="off"
            />
          </label>

          <div className={styles.divider} />

          <div className={styles.sectionHeading}>
            <span>02</span>
            <div>
              <h2>条件の順番</h2>
              <p>矢印で実施順を入れ替え</p>
            </div>
          </div>
          <div className={styles.orderList}>
            {order.map((condition, index) => {
              const item = CONDITIONS[condition];
              return (
                <div className={`${styles.orderItem} ${styles[item.color]}`} key={condition}>
                  <span className={styles.orderNumber}>{String(index + 1).padStart(2, "0")}</span>
                  <div className={styles.orderName}>
                    <small>{item.label}</small>
                    <strong>{item.name}条件</strong>
                  </div>
                  <div className={styles.moveButtons}>
                    <button
                      type="button"
                      onClick={() => moveCondition(index, -1)}
                      disabled={index === 0}
                      aria-label={`${item.name}条件を上へ`}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => moveCondition(index, 1)}
                      disabled={index === order.length - 1}
                      aria-label={`${item.name}条件を下へ`}
                    >
                      ↓
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <div className={styles.divider} />

          <div className={styles.sectionHeading}>
            <span>03</span>
            <div>
              <h2>使用する素材</h2>
              <p>登録したURLの番号を選択</p>
            </div>
          </div>
          <div className={styles.selectionCards}>
            {order.map((condition) => (
              <div className={styles.selectionRow} key={condition}>
                <span>{CONDITIONS[condition].name}条件</span>
                <SelectField
                  label="映画予告"
                  value={selections.trailers[condition]}
                  count={8}
                  onChange={(value) => updateTrailer(condition, value)}
                />
              </div>
            ))}
            <div className={styles.selectionRow}>
              <span>日常動画条件</span>
              <SelectField
                label="日常動画"
                value={selections.dailyVideo}
                count={10}
                onChange={(value) =>
                  setSelections((current) => ({ ...current, dailyVideo: value }))
                }
              />
              <SelectField
                label="理解度テスト"
                value={selections.comprehensionTest}
                count={10}
                onChange={(value) =>
                  setSelections((current) => ({ ...current, comprehensionTest: value }))
                }
              />
            </div>
          </div>

          <button
            type="button"
            className={styles.settingsToggle}
            onClick={() => setShowUrlSettings((current) => !current)}
            aria-expanded={showUrlSettings}
          >
            <span>URL対応表を{showUrlSettings ? "閉じる" : "編集する"}</span>
            <strong>{showUrlSettings ? "−" : "+"}</strong>
          </button>
        </section>

        <aside className={styles.preview} aria-label="生成されたメール">
          <div className={styles.previewTop}>
            <div>
              <p>LIVE PREVIEW</p>
              <h2>生成テキスト</h2>
            </div>
            <span className={missingUrlCount ? styles.warning : styles.ready}>
              {missingUrlCount ? `未登録 ${missingUrlCount}件` : "送信準備OK"}
            </span>
          </div>
          <textarea value={mailText} readOnly aria-label="生成されたメール本文" />
          <button type="button" className={styles.copyButton} onClick={copyMail}>
            <span>{copied ? "コピーしました" : "本文をコピー"}</span>
            <span aria-hidden="true">{copied ? "✓" : "⌘C"}</span>
          </button>
          <p className={styles.finalNote}>実験後アンケートは常に最後に配置されます</p>
        </aside>
      </div>

      {showUrlSettings && (
        <section className={styles.urlSettings}>
          <div className={styles.urlSettingsTitle}>
            <p>URL LIBRARY</p>
            <h2>番号とURLの対応表</h2>
            <span>入力内容はこのブラウザに自動保存されます。</span>
          </div>
          <UrlGroup
            title="2分間の映画予告映像"
            description="8種類"
            urlKey="trailers"
            count={8}
            urls={urls}
            onUrlChange={updateUrl}
          />
          <UrlGroup
            title="日常動画"
            description="10種類"
            urlKey="dailyVideos"
            count={10}
            urls={urls}
            onUrlChange={updateUrl}
          />
          <UrlGroup
            title="理解度テスト"
            description="10種類"
            urlKey="comprehensionTests"
            count={10}
            urls={urls}
            onUrlChange={updateUrl}
          />
        </section>
      )}
    </main>
  );
}
