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
  downloadMediaMessage,
} from "@whiskeysockets/baileys";

// Prevent Baileys internal timeouts (prekey upload, etc.) from crashing the process
process.on("unhandledRejection", (reason) => {
  process.stdout.write(`[WA-BRIDGE] unhandledRejection (ignored): ${reason?.message || reason}\n`);
});
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

const logger = pino({ level: "warn" });
const silentLogger = pino({ level: "silent" });

// Suppress libsignal noise written directly to stdout/stderr
const _SIGNAL_NOISE = ["Bad MAC", "Failed to decrypt message", "Closing open session", "Closing session: SessionEntry", "_chains"];
const _isNoisy = (s) => typeof s === "string" && _SIGNAL_NOISE.some(p => s.includes(p));
const _origStdoutWrite = process.stdout.write.bind(process.stdout);
const _origStderrWrite = process.stderr.write.bind(process.stderr);
process.stdout.write = (chunk, ...rest) => _isNoisy(chunk?.toString()) ? true : _origStdoutWrite(chunk, ...rest);
process.stderr.write = (chunk, ...rest) => _isNoisy(chunk?.toString()) ? true : _origStderrWrite(chunk, ...rest);

// ── State ─────────────────────────────────────────────────────────────────────
/** @type {Map<string, { socket: any, qrListeners: Set<(qr: string) => void>, status: string, lidMap: Map<string,string> }>} */
const channels = new Map();
/** Track channels currently being started to prevent duplicate sockets */
const starting = new Set();
/** Pending reconnect timers — prevents double-reconnect from multiple close events */
const reconnectTimers = new Map();

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
  const key = String(channelId);
  if (starting.has(key)) return channels.get(key);
  if (channels.has(key)) return channels.get(key); // already running
  starting.add(key);
  const dir = authPath || authDir(channelId);
  ensureDir(dir);

  let state, saveCreds, version;
  try {
    ({ state, saveCreds } = await useMultiFileAuthState(dir));
    ({ version } = await fetchLatestBaileysVersion());
  } catch (err) {
    starting.delete(String(channelId));
    throw err;
  }

  // In-memory cache of recently sent messages for retry support.
  // WA will ask us to resend if the recipient's decryption fails.
  const recentSent = new Map(); // msgId → proto.IMessage

  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, silentLogger),
    },
    logger: silentLogger,
    generateHighQualityLinkPreview: false,
    // Required: lets Baileys resend our messages when recipient requests retry
    getMessage: async (key) => {
      return recentSent.get(key.id) || undefined;
    },
  });

  const lastMsgCache = new Map(); // bufKey → last raw Baileys WAMessage (never serialized)

  const entry = {
    socket: sock,
    qrListeners: new Set(),
    status: "pending_qr",
    lastQr: null,        // last QR PNG so new SSE listeners can replay it
    authDir: dir,
    lidMap: new Map(),   // lid JID → phone JID (from lid-mapping.update)
    recentSent,
    lastMsgCache,
  };
  channels.set(String(channelId), entry);
  starting.delete(String(channelId));

  // ── Events ──────────────────────────────────────────────────────────────────

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      entry.status = "pending_qr";
      // Render as base64 PNG so the frontend doesn't need a QR library
      const qrPng = await QRCode.toDataURL(qr, { width: 280, margin: 2 });
      entry.lastQr = qrPng;
      for (const listener of entry.qrListeners) {
        listener(qrPng);
      }
    }

    if (connection === "open") {
      entry.status = "connected";
      entry.lastQr = null;
      const phone = sock.user?.id?.split(":")[0] || null;
      logger.info({ channelId, phone }, "WhatsApp connected");
      await updateChannelStatus(channelId, "connected", phone);
      // Announce global available presence so typing indicators are visible to contacts
      sock.sendPresenceUpdate("available").catch(() => {});
    }

    if (connection === "close") {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const shouldReconnect = reason !== DisconnectReason.loggedOut;
      _origStdoutWrite(`[WA-BRIDGE] connection closed channelId=${channelId} reason=${reason} shouldReconnect=${shouldReconnect} error=${lastDisconnect?.error?.message}\n`);

      logger.info({ channelId, reason, shouldReconnect }, "WhatsApp disconnected");
      entry.status = "disconnected";

      if (shouldReconnect) {
        channels.delete(String(channelId));
        // Cancel any pending reconnect before scheduling a new one
        if (reconnectTimers.has(String(channelId))) {
          clearTimeout(reconnectTimers.get(String(channelId)));
        }
        reconnectTimers.set(String(channelId), setTimeout(() => {
          reconnectTimers.delete(String(channelId));
          startChannel(channelId, dir);
        }, 500));
      } else {
        await updateChannelStatus(channelId, "disconnected");
        // Logged out — remove auth state
        channels.delete(String(channelId));
        fs.rmSync(dir, { recursive: true, force: true });
      }
    }
  });

  // Helper: resolve @lid JID to @s.whatsapp.net using our lid map
  function resolveLid(jid) {
    if (!jid || !jid.endsWith("@lid")) return jid;
    return entry.lidMap.get(jid) ?? jid;
  }

  // LID resolution: populate lidMap from every event that may carry the mapping
  function storeLidMapping(lid, pn) {
    if (!lid || !pn) return;
    const phoneJid = pn.includes("@") ? pn : `${pn}@s.whatsapp.net`;
    if (!entry.lidMap.has(lid)) {
      entry.lidMap.set(lid, phoneJid);
      _origStdoutWrite(`[WA-BRIDGE] lid-mapping stored: ${lid} → ${phoneJid}\n`);
    }
  }

  // lid-mapping.update: fires as single object or array depending on Baileys version
  sock.ev.on("lid-mapping.update", (data) => {
    const items = Array.isArray(data) ? data : [data];
    for (const { lid, pn } of items) storeLidMapping(lid, pn);
  });

  // messaging-history.set: bulk load on reconnect
  sock.ev.on("messaging-history.set", ({ lidPnMappings }) => {
    if (!lidPnMappings?.length) return;
    for (const { lid, pn } of lidPnMappings) storeLidMapping(lid, pn);
    _origStdoutWrite(`[WA-BRIDGE] messaging-history: loaded ${lidPnMappings.length} lid mappings\n`);
  });

  // contacts.upsert/update: some Baileys builds populate phoneNumber here
  function indexContacts(contacts) {
    for (const c of contacts) {
      if (c.id?.endsWith("@lid") && c.phoneNumber) storeLidMapping(c.id, c.phoneNumber);
      if (c.lid && c.id && !c.id.endsWith("@lid")) storeLidMapping(c.lid, c.id);
    }
  }
  sock.ev.on("contacts.upsert", indexContacts);
  sock.ev.on("contacts.update", indexContacts);

  // Dedup: per-socket-instance seen message IDs
  const seenMsgIds = new Set();

  // Per-chat debounce buffer: key = phone prefix, value = { timer, lines, meta, lastMsg }
  const chatBuffers = new Map();
  const DEBOUNCE_MS = 1000;

  function flushChat(bufKey) {
    const buf = chatBuffers.get(bufKey);
    if (!buf) return;
    // Store the last Baileys msg object in the per-entry cache before clearing the buffer
    if (buf.lastMsg) lastMsgCache.set(bufKey, buf.lastMsg);
    chatBuffers.delete(bufKey);
    const combinedText = buf.lines.join("\n");
    _origStdoutWrite(`[WA-BRIDGE] flushing bufKey=${bufKey} lines=${buf.lines.length} text=${JSON.stringify(combinedText)}\n`);
    notifyBackend(channelId, {
      ...buf.meta,
      message_text: combinedText,
      message_count: buf.lines.length,
    }).catch((e) => {
      _origStdoutWrite(`[WA-BRIDGE] notifyBackend error: ${e}\n`);
    });
  }

  // Track when this socket instance was created so we can process
  // "append" (history-sync) messages that arrived during a reconnect window
  const socketStartedAt = Math.floor(Date.now() / 1000);

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    _origStdoutWrite(`[WA-BRIDGE] upsert type=${type} count=${messages.length}\n`);

    // "append" = history sync. Skip old history but process messages that
    // arrived while we were briefly disconnected (timestamp >= socketStartedAt)
    if (type !== "notify") {
      if (type !== "append") return;
      // Only process append messages that are newer than this socket instance
      messages = messages.filter(m => {
        const ts = m.messageTimestamp;
        const sec = typeof ts === "object" ? ts?.low ?? ts?.toNumber?.() ?? ts : ts;
        return !m.key.fromMe && sec >= socketStartedAt;
      });
      if (messages.length === 0) return;
      _origStdoutWrite(`[WA-BRIDGE] processing ${messages.length} recent append messages\n`);
    }

    for (const msg of messages) {
      if (msg.key.fromMe) continue; // Ignore outgoing messages

      const msgId = `${channelId}:${msg.key.id}`;
      if (seenMsgIds.has(msgId)) continue;

      const rawChatId = msg.key.remoteJid;
      const rawSender = msg.key.participant || msg.key.remoteJid;
      // senderPn is set on multi-device for DMs — it's the actual phone number
      const senderPn = msg.key.senderPn || msg.key.phoneNumber;

      function resolveJid(jid) {
        if (!jid?.endsWith("@lid")) return jid;
        // Prefer senderPn (actual phone number WhatsApp provides)
        if (senderPn) return senderPn.includes("@") ? senderPn : `${senderPn}@s.whatsapp.net`;
        // Fall back to lidMap populated from contacts events
        return resolveLid(jid);
      }

      const waChatId = resolveJid(rawChatId);
      const waSender = resolveJid(rawSender);
      // If still a @lid after resolution, extract numeric part and treat as phone number
      // LID format on some WA versions: the numeric part IS the phone without country code prefix
      // but we can't reliably convert — store as waLid so backend can match by lid
      const waLid = rawChatId?.endsWith("@lid") ? rawChatId : (rawSender?.endsWith("@lid") ? rawSender : null);
      const isGroup = rawChatId?.endsWith("@g.us") || false;
      let waGroupName = null;
      if (isGroup) {
        try {
          const meta = await sock.groupMetadata(rawChatId);
          waGroupName = meta?.subject || null;
        } catch (_) {}
      }

      let text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        null;

      _origStdoutWrite(`[WA-BRIDGE] text=${JSON.stringify(text)} msgKeys=${Object.keys(msg.message||{}).join(",")} waChatId=${waChatId}\n`);

      // Transcribe voice notes via backend
      if (!text && msg.message?.audioMessage) {
        // Mark seen immediately so a duplicate arrival on the other JID doesn't also transcribe
        seenMsgIds.add(msgId);
        if (seenMsgIds.size > 500) { const first = seenMsgIds.values().next().value; seenMsgIds.delete(first); }
        try {
          const audioBuffer = await downloadMediaMessage(msg, "buffer", {});
          // POST multipart to backend /wa/transcribe
          const boundary = `----WA${Date.now()}`;
          const crlf = "\r\n";
          const bodyParts = [
            `--${boundary}${crlf}`,
            `Content-Disposition: form-data; name="file"; filename="audio.ogg"${crlf}`,
            `Content-Type: audio/ogg${crlf}${crlf}`,
          ];
          const tail = `${crlf}--${boundary}--${crlf}`;
          const head = Buffer.from(bodyParts.join(""));
          const tailBuf = Buffer.from(tail);
          const body = Buffer.concat([head, audioBuffer, tailBuf]);

          const resp = await axios.post(
            `${FASTAPI_URL}/wa/transcribe`,
            body,
            { headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` }, responseType: "json", timeout: 120000 }
          );
          text = resp.data?.text || null;
          _origStdoutWrite(`[WA-BRIDGE] transcribed audio: ${JSON.stringify(text)}\n`);
        } catch (err) {
          _origStdoutWrite(`[WA-BRIDGE] audio transcription failed: ${err.message}\n`);
        }
      }

      // Don't add to seenMsgIds if no text — messages.update may deliver the decrypted content later
      if (!text) continue;

      // Mark as seen only after we confirm there's processable content
      seenMsgIds.add(msgId);
      if (seenMsgIds.size > 500) {
        const first = seenMsgIds.values().next().value;
        seenMsgIds.delete(first);
      }

      // Use phone-number prefix as buffer key to handle @lid vs @s.whatsapp.net inconsistency
      const bufKey = waChatId.split("@")[0];

      // Buffer messages per chat — flush after DEBOUNCE_MS of silence
      if (chatBuffers.has(bufKey)) {
        const buf = chatBuffers.get(bufKey);
        clearTimeout(buf.timer);
        buf.lines.push(text);
        buf.lastMsg = msg;
        buf.timer = setTimeout(() => flushChat(bufKey), DEBOUNCE_MS);
      } else {
        chatBuffers.set(bufKey, {
          lines: [text],
          lastMsg: msg,
          meta: { wa_chat_id: waChatId, wa_sender: waSender, wa_lid: waLid, is_group: isGroup, wa_group_name: waGroupName },
          timer: setTimeout(() => flushChat(bufKey), DEBOUNCE_MS),
        });
      }
    }
  });

  // Handle messages that arrived with null content (pending key exchange) and were later decrypted
  sock.ev.on("messages.update", (updates) => {
    for (const update of updates) {
      if (!update.update?.message) continue; // no content update
      if (update.key.fromMe) continue;

      const msgId = `${channelId}:${update.key.id}`;
      if (seenMsgIds.has(msgId)) continue; // already processed
      seenMsgIds.add(msgId);

      const msg = update.update.message;
      const text =
        msg.conversation ||
        msg.extendedTextMessage?.text ||
        msg.imageMessage?.caption ||
        null;

      _origStdoutWrite(`[WA-BRIDGE] messages.update decrypted id=${update.key.id} text=${JSON.stringify(text)}\n`);
      if (!text) continue;

      const rawChatId = update.key.remoteJid;
      const rawSender = update.key.participant || update.key.remoteJid;
      function resolveJidU(jid) {
        if (!jid?.endsWith("@lid")) return jid;
        return resolveLid(jid);
      }
      const waChatId = resolveJidU(rawChatId);
      const waSender = resolveJidU(rawSender);
      const isGroup = rawChatId?.endsWith("@g.us") || false;
      const bufKey = waChatId.split("@")[0];

      // Reconstruct a minimal WAMessage-shaped object for quoting
      const syntheticMsg = { key: update.key, message: update.update.message };
      if (chatBuffers.has(bufKey)) {
        const buf = chatBuffers.get(bufKey);
        clearTimeout(buf.timer);
        buf.lines.push(text);
        buf.lastMsg = syntheticMsg;
        buf.timer = setTimeout(() => flushChat(bufKey), DEBOUNCE_MS);
      } else {
        chatBuffers.set(bufKey, {
          lines: [text],
          lastMsg: syntheticMsg,
          meta: { wa_chat_id: waChatId, wa_sender: waSender, wa_lid: null, is_group: isGroup },
          timer: setTimeout(() => flushChat(bufKey), DEBOUNCE_MS),
        });
      }
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

/** Typing presence — composing or paused */
app.post("/channels/:id/typing", async (req, res) => {
  const { id } = req.params;
  const { wa_chat_id, action } = req.body; // action: "composing" | "paused"
  const entry = channels.get(id);
  if (!entry || entry.status !== "connected") {
    return res.status(503).json({ error: "Channel not connected" });
  }
  try {
    _origStdoutWrite(`[WA-BRIDGE] typing ${action} → ${wa_chat_id}\n`);
    if (action !== "paused") {
      // Subscribe to presence for this chat so WA relays our typing to participants
      await entry.socket.presenceSubscribe(wa_chat_id).catch(() => {});
      await entry.socket.sendPresenceUpdate("available", wa_chat_id);
    }
    await entry.socket.sendPresenceUpdate(action === "paused" ? "paused" : "composing", wa_chat_id);
    res.json({ status: "ok" });
  } catch (err) {
    _origStdoutWrite(`[WA-BRIDGE] typing presence error: ${err?.message || err}\n`);
    res.status(500).json({ error: String(err) });
  }
});

/** Send an outgoing message */
app.post("/channels/:id/send", async (req, res) => {
  const { id } = req.params;
  const { wa_chat_id, text, should_quote } = req.body;

  const entry = channels.get(id);
  if (!entry || entry.status !== "connected") {
    return res.status(503).json({ error: "Channel not connected" });
  }

  try {
    // Look up the cached Baileys message object (never serialized — lives in sidecar memory)
    const bufKey = wa_chat_id.split("@")[0];
    const cachedMsg = should_quote ? entry.lastMsgCache?.get(bufKey) : null;
    const sendOpts = cachedMsg ? { quoted: cachedMsg } : {};
    const sent = await entry.socket.sendMessage(wa_chat_id, { text }, sendOpts);
    // Cache for retry: if recipient's decryption fails, WA asks us to resend
    if (sent?.key?.id) {
      entry.recentSent.set(sent.key.id, sent.message);
      // Keep cache bounded to last 50 sent messages
      if (entry.recentSent.size > 50) {
        entry.recentSent.delete(entry.recentSent.keys().next().value);
      }
    }
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

  // Replay last QR immediately if one was already generated before this listener connected
  if (entry.lastQr) {
    onQR(entry.lastQr);
  }

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
      // Reset status to disconnected first — backend may show stale "connected" from a previous run
      await updateChannelStatus(channelId, "disconnected").catch(() => {});
      logger.info({ channelId }, "Auto-reconnecting channel on startup");
      startChannel(channelId, dir).catch((err) =>
        logger.warn({ err, channelId }, "Auto-reconnect failed")
      );
    }
  } catch (err) {
    logger.warn({ err }, "Failed to scan auth dir for auto-reconnect");
  }
});
