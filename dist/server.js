import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PET_DIR = path.join(os.homedir(), ".opencode", "pet");
const WRITE_THROTTLE = 400;
const DISABLE_FILE = path.join(PET_DIR, "disabled");
const TOKEN_FILE = path.join(PET_DIR, "token");
const isDisabled = () => fs.existsSync(DISABLE_FILE);

const fileFor = (id) =>
  path.join(PET_DIR, `status-${String(id).replace(/[^a-zA-Z0-9_-]/g, "_")}.json`);

const ensureToken = () => {
  try {
    if (!fs.existsSync(TOKEN_FILE)) {
      fs.writeFileSync(TOKEN_FILE, Array.from(crypto.getRandomValues(new Uint8Array(24))).map(b => b.toString(16).padStart(2, "0")).join(""), { mode: 0o600 });
    }
    return fs.readFileSync(TOKEN_FILE, "utf8").trim();
  } catch {
    return "";
  }
};

const PetPlugin = async ({ directory, client }) => {
  fs.mkdirSync(PET_DIR, { recursive: true });
  const cwd = directory || process.cwd();
  const token = ensureToken();
  const sessions = new Map();
  const ACTIVE = new Set(["busy", "thinking", "error", "retry", "celebrating"]);

  const defaultSession = () => ({
    state: "idle",
    message: "",
    prevState: "",
    lastWrite: 0,
    lastActive: 0,
    toolName: "",
    toolArgs: "",
    toolLabel: "",
    direction: "left",
    title: "",
  });

  const touchActive = (s) => { s.lastActive = Date.now(); };

  const writeStatus = (id, force = false) => {
    const s = sessions.get(id);
    if (!s) return;
    const now = Date.now();
    if (!force && s.state === s.prevState && now - (s.lastWrite || 0) < WRITE_THROTTLE) return;
    s.lastWrite = now;
    try {
      fs.writeFileSync(
        fileFor(id),
        JSON.stringify({ sessionID: id, state: s.state, prevState: s.prevState, message: s.message, toolName: s.toolName || "", toolArgs: s.toolArgs || "", toolLabel: s.toolLabel || "", direction: s.direction || "left", title: s.title || "", cwd, updatedAt: now })
      );
      s.prevState = s.state;
    } catch {}
  };

  const setState = (id, state, message) => {
    const prev = sessions.get(id);
    const prevState = prev ? prev.state : "idle";
    const s = sessions.get(id) || defaultSession();
    s.prevState = prevState;
    s.state = state;
    touchActive(s);
    if (message !== undefined) s.message = String(message).replace(/\s+/g, " ").trim().slice(0, 120);
    sessions.set(id, s);
    writeStatus(id, state !== s.prevState);
  };

  const touchTool = (id, toolName, toolArgs) => {
    const s = sessions.get(id) || defaultSession();
    touchActive(s);
    if (toolName) s.direction = s.direction === "left" ? "right" : "left";
    s.toolName = toolName || "";
    s.toolArgs = toolArgs || "";
    s.toolLabel = formatTool(toolName, toolArgs);
    sessions.set(id, s);
    writeStatus(id, true);
  };

  const fetchTitle = async (sessionID) => {
    try {
      if (!client?.session?.get) return "";
      const info = await client.session.get(sessionID);
      const t = info?.title || info?.name || "";
      return String(t).trim().slice(0, 60);
    } catch {
      return "";
    }
  };

  const removeSession = (id) => {
    sessions.delete(id);
    try { fs.unlinkSync(fileFor(id)); } catch {}
  };

  if (isDisabled()) {
    return {
      dispose: async () => {},
      event: async () => {},
      "tool.execute.before": async () => {},
      "tool.execute.after": async () => {},
    };
  }

  const heartbeat = setInterval(() => {
    const now = Date.now();
    for (const id of [...sessions.keys()]) {
      const s = sessions.get(id);
      if (!s) continue;
      if (now - (s.lastActive || 0) > 300_000) {
        // no real activity for 5 min -> session is dead, clean it up
        removeSession(id);
      } else if (ACTIVE.has(s.state)) {
        // only keep ACTIVE sessions fresh; idle/done ones age out (the pet
        // marks them stale ~25s later, the dashboard drops them, the file
        // is pruned after 5 min)
        writeStatus(id, true);
      }
    }
  }, 10_000);

  return {
    dispose: async () => {
      clearInterval(heartbeat);
      for (const id of [...sessions.keys()]) removeSession(id);
      sessions.clear();
    },
    event: async ({ event }) => {
      const props = event.properties || {};
      const sessionID = props.sessionID;
      if (!sessionID) return;
      switch (event.type) {
        case "session.created": {
          setState(sessionID, "idle");
          const title = await fetchTitle(sessionID);
          if (title) {
            const s = sessions.get(sessionID) || defaultSession();
            s.title = title;
            sessions.set(sessionID, s);
            writeStatus(sessionID, true);
          }
          break;
        }
        case "session.status": {
          const type = props.status?.type;
          if (type === "busy" || type === "retry") setState(sessionID, "busy");
          else if (type === "idle") setState(sessionID, "idle");
          else if (type === "thinking") setState(sessionID, "thinking");
          break;
        }
        case "message.part.updated": {
          const part = props.part;
          if (part && part.type === "text" && part.text) {
            const s = sessions.get(sessionID);
            if (s) { s.toolName = ""; s.toolArgs = ""; }
            setState(sessionID, "busy", part.text);
          }
          break;
        }
        case "session.error":
          setState(sessionID, "error", "Something went wrong");
          break;
        case "session.idle": {
          const s = sessions.get(sessionID);
          const wasBusy = !!(s && s.prevState === "busy");
          setState(sessionID, "idle", "Done");
          if (wasBusy) {
            setState(sessionID, "celebrating", "Done!");
            setTimeout(() => { if (sessions.has(sessionID)) setState(sessionID, "idle", ""); }, 2000);
          }
          break;
        }
        case "session.deleted":
          removeSession(sessionID);
          break;
      }
    },
    "tool.execute.before": async (input) => {
      const sessionID = input.sessionID;
      if (!sessionID) return;
      touchTool(sessionID, input.tool, snippetOf(input.args));
    },
    "tool.execute.after": async (input) => {
      const sessionID = input.sessionID;
      if (!sessionID) return;
      touchTool(sessionID, "", "");
    },
  };
};

function snippetOf(args) {
  try {
    const a = typeof args === "string" ? args : JSON.stringify(args);
    return String(a).replace(/\s+/g, " ").trim().slice(0, 60);
  } catch {
    return "";
  }
}

function formatTool(toolName, toolArgs) {
  if (!toolName) return "";
  const clean = toolName.replace(/[^a-zA-Z0-9_-]/g, " ").trim();
  if (!toolArgs) return clean;
  try {
    const args = typeof toolArgs === "string" ? JSON.parse(toolArgs) : toolArgs;
    if (["read", "edit", "write"].includes(clean) && args.filePath) return `${clean} ${path.basename(args.filePath)}`;
    if (clean === "bash" && args.command) {
      const cmd = String(args.command).replace(/\s+/g, " ").trim().slice(0, 50);
      return `${clean} ${cmd}`;
    }
    if ((clean === "grep" || clean === "glob") && args.pattern) {
      let out = `${clean} "${args.pattern}"`;
      if (args.path) out += ` ${args.path}`;
      if (args.type) out += ` type:${args.type}`;
      return out;
    }
    if ((clean === "webfetch" || clean === "web_fetch") && args.url) return `${clean} ${args.url}`;
    if (clean === "write" && args.filePath && args.content) return `${clean} ${path.basename(args.filePath)} (${String(args.content).length}b)`;
    if (clean === "edit" && args.filePath && args.find && args.replace) {
      const findLen = Math.min(String(args.find).length, 20);
      return `${clean} ${path.basename(args.filePath)} (${findLen} chars)`;
    }
    return `${clean} ${toolArgs}`;
  } catch {
    return `${clean} ${toolArgs}`;
  }
}

export default PetPlugin;
