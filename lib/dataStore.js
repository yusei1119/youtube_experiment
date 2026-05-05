import fs from "fs";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "data");
const SESSIONS_PATH = path.join(DATA_DIR, "sessions.json");
const LOGS_PATH = path.join(DATA_DIR, "logs.jsonl");

function ensureDataFiles() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }

  if (!fs.existsSync(SESSIONS_PATH)) {
    fs.writeFileSync(SESSIONS_PATH, "[]", "utf-8");
  }

  if (!fs.existsSync(LOGS_PATH)) {
    fs.writeFileSync(LOGS_PATH, "", "utf-8");
  }
}

export function readSessions() {
  ensureDataFiles();
  const raw = fs.readFileSync(SESSIONS_PATH, "utf-8");
  return JSON.parse(raw);
}

export function saveSessions(sessions) {
  ensureDataFiles();
  fs.writeFileSync(SESSIONS_PATH, JSON.stringify(sessions, null, 2), "utf-8");
}

export function addSession(session) {
  const sessions = readSessions();
  sessions.push(session);
  saveSessions(sessions);
  return session;
}

export function findSession(sessionId) {
  const sessions = readSessions();
  return sessions.find((s) => s.session_id === sessionId);
}

export function updateSession(sessionId, patch) {
  const sessions = readSessions();
  const index = sessions.findIndex((s) => s.session_id === sessionId);

  if (index === -1) return null;

  sessions[index] = {
    ...sessions[index],
    ...patch,
    updated_at: new Date().toISOString(),
  };

  saveSessions(sessions);
  return sessions[index];
}

export function appendLog(log) {
  ensureDataFiles();
  fs.appendFileSync(LOGS_PATH, JSON.stringify(log) + "\n", "utf-8");
}