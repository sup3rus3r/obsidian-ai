/**
 * Obsidian AI — WhatsApp Bridge (Baileys sidecar)
 *
 * Manages one Baileys WA socket per channel_id.
 * Receives messages and forwards them to the FastAPI backend.
 * Exposes HTTP endpoints for the backend to send outgoing messages and stream QR codes.
 */

import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} from "@whiskeysockets/baileys";
import express from "express";
import axios from "axios";
import { Boom } from "@hapi/boom";
import QRCode from "qrcode";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import pino from "pino";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── Config ────────────────────────────────────────────────────────────────────
const PORT = parseInt(process.env.WA_BRIDGE_PORT || "3200");
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8001";
const AUTH_BASE_DIR = process.env.WA_AUTH_DIR || path.join(__dirname, "auth");

const logger = pino({ level: "info" });

// ── State ─────────────────────────────────────────────────────────────────────
/** @type {Map<string, { socket: any, qrListeners: Set<(qr: string) => void>, status: string }>} */
const channels = new Map();

// ── Helpers ───────────────────────────────────────────────────────────────────

function authDir(channelId) {
  return path.join(AUTH_BASE_DIR, String(channelId));
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

async function notifyBackend(channelId, payload) {
  try {
    await axios.post(`${FASTAPI_URL}/wa/incoming`, { channel_id: channelId, ...payload });
  } catch (err) {
    logger.warn({ err }, `Failed to notify backend for channel ${channelId}`);
  }
}

async function updateChannelStatus(channelId, status, waPhone = null) {
  try {
    const body = { status };
    if (waPhone) body.wa_phone = waPhone;
    await axios.patch(`${FASTAPI_URL}/wa/channels/${channelId}/status`, body);
  } catch (_) {
    // Best-effort — backend may not be ready yet
  }
}

// ── Socket lifecycle ──────────────────────────────────────────────────────────

async function startChannel(channelId, authPath) {
  const dir = authPath || authDir(channelId);
  ensureDir(dir);

  const { state, saveCreds } = await useMultiFileAuthState(dir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    printQRInTerminal: true,
    logger: logger.child({ channel: channelId }),
    generateHighQualityLinkPreview: false,
  });

  const entry = {
    socket: sock,
    qrListeners: new Set(),
    status: "pending_qr",
    authDir: dir,
  };
  channels.set(String(channelId), entry);

  // ── Events ──────────────────────────────────────────────────────────────────

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      entry.status = "pending_qr";
      // Render as base64 PNG so the frontend doesn't need a QR library
      const qrPng = await QRCode.toDataURL(qr, { width: 280, margin: 2 });
      for (const listener of entry.qrListeners) {
        listener(qrPng);
      }
    }

    if (connection === "open") {
      entry.status = "connected";
      const phone = sock.user?.id?.split(":")[0] || null;
      logger.info({ channelId, phone }, "WhatsApp connected");
      await updateChannelStatus(channelId, "connected", phone);
    }

    if (connection === "close") {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const shouldReconnect = reason !== DisconnectReason.loggedOut;

      logger.info({ channelId, reason, shouldReconnect }, "WhatsApp disconnected");
      entry.status = "disconnected";
      await updateChannelStatus(channelId, "disconnected");

      if (shouldReconnect) {
        // Back-off and reconnect
        setTimeout(() => startChannel(channelId, dir), 5000);
      } else {
        // Logged out — remove auth state
        channels.delete(String(channelId));
        fs.rmSync(dir, { recursive: true, force: true });
      }
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    logger.info({ channelId, type, count: messages.length }, "messages.upsert received");
    if (type !== "notify") return;

    for (const msg of messages) {
      logger.info({ channelId, fromMe: msg.key.fromMe, remoteJid: msg.key.remoteJid }, "processing message");
      if (msg.key.fromMe) continue; // Ignore outgoing messages

      const waChatId = msg.key.remoteJid;
      const waSender = msg.key.participant || msg.key.remoteJid; // participant set in groups
      const isGroup = waChatId?.endsWith("@g.us") || false;

      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        null;

      logger.info({ channelId, waChatId, waSender, hasText: !!text }, "message details");
      if (!text) continue; // Skip non-text messages for now

      await notifyBackend(channelId, {
        wa_chat_id: waChatId,
        wa_sender: waSender,
        message_text: text,
        is_group: isGroup,
      });
    }
  });

  return entry;
}

function stopChannel(channelId) {
  const entry = channels.get(String(channelId));
  if (!entry) return;
  try {
    entry.socket.end(undefined);
  } catch (_) {}
  channels.delete(String(channelId));
}

// ── Express app ───────────────────────────────────────────────────────────────

const app = express();
app.use(express.json());

/** Start / connect a channel */
app.post("/channels/:id/start", async (req, res) => {
  const { id } = req.params;
  const { auth_path } = req.body || {};

  // Stop existing socket if any
  if (channels.has(id)) stopChannel(id);

  try {
    await startChannel(id, auth_path);
    res.json({ status: "starting" });
  } catch (err) {
    logger.error({ err }, "Failed to start channel");
    res.status(500).json({ error: String(err) });
  }
});

/** Gracefully disconnect a channel */
app.post("/channels/:id/stop", (req, res) => {
  stopChannel(req.params.id);
  res.json({ status: "stopped" });
});

/** Send an outgoing message */
app.post("/channels/:id/send", async (req, res) => {
  const { id } = req.params;
  const { wa_chat_id, text } = req.body;

  const entry = channels.get(id);
  if (!entry || entry.status !== "connected") {
    return res.status(503).json({ error: "Channel not connected" });
  }

  try {
    await entry.socket.sendMessage(wa_chat_id, { text });
    res.json({ status: "sent" });
  } catch (err) {
    logger.error({ err }, "Failed to send message");
    res.status(500).json({ error: String(err) });
  }
});

/** SSE stream of QR / status events for a channel */
app.get("/channels/:id/events", (req, res) => {
  const { id } = req.params;

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  const entry = channels.get(id);
  if (!entry) {
    res.write(`data: ${JSON.stringify({ type: "error", message: "Channel not started" })}\n\n`);
    return res.end();
  }

  // If already connected, send connected event immediately
  if (entry.status === "connected") {
    res.write(`data: ${JSON.stringify({ type: "connected" })}\n\n`);
    return res.end();
  }

  const onQR = (qr) => {
    res.write(`data: ${JSON.stringify({ type: "qr", qr })}\n\n`);
  };

  entry.qrListeners.add(onQR);

  // Also watch for connection open via polling the entry status
  const poll = setInterval(() => {
    if (entry.status === "connected") {
      clearInterval(poll);
      entry.qrListeners.delete(onQR);
      res.write(`data: ${JSON.stringify({ type: "connected" })}\n\n`);
      res.end();
    }
  }, 1000);

  req.on("close", () => {
    clearInterval(poll);
    entry.qrListeners.delete(onQR);
  });
});

/** Health check */
app.get("/health", (_, res) => {
  const channelStatuses = {};
  for (const [id, entry] of channels.entries()) {
    channelStatuses[id] = entry.status;
  }
  res.json({ status: "ok", channels: channelStatuses });
});

// ── Internal status update endpoint (called by this sidecar back to FastAPI) ─
// Actually called via updateChannelStatus() — no route needed here.

app.listen(PORT, async () => {
  logger.info(`WhatsApp bridge listening on port ${PORT}`);
  logger.info(`Forwarding to FastAPI at ${FASTAPI_URL}`);
  ensureDir(AUTH_BASE_DIR);

  // Auto-reconnect channels that have saved auth state
  try {
    const entries = fs.readdirSync(AUTH_BASE_DIR, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const channelId = entry.name;
      const dir = path.join(AUTH_BASE_DIR, channelId);
      // Only reconnect if creds.json exists (i.e. was previously authenticated)
      if (!fs.existsSync(path.join(dir, "creds.json"))) continue;
      logger.info({ channelId }, "Auto-reconnecting channel on startup");
      startChannel(channelId, dir).catch((err) =>
        logger.warn({ err, channelId }, "Auto-reconnect failed")
      );
    }
  } catch (err) {
    logger.warn({ err }, "Failed to scan auth dir for auto-reconnect");
  }
});
