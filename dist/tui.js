import { createElement, insert, setProp, createComponent } from "@opentui/solid";
import { createSignal, createEffect, onCleanup, Show, For } from "solid-js";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

console.log("[PET-PLUGIN] TOP LEVEL LOADED, path:", import.meta.url);

const FRAMES = {
  idle: [
    ["   /\\_/\\", "  ( o.o )", "   > ^ <"],
    ["   /\\_/\\", "  ( -.- )", "   > ^ <"],
  ],
  busy: [
    ["   /\\_/\\", "  ( >.< )", "   > w <"],
    ["   /\\_/\\", "  ( O.O )", "   > w <"],
    ["   /\\_/\\", "  ( o.o )", "   > w <"],
    ["   /\\_/\\", "  ( >.< )", "   > w <"],
  ],
  thinking: [
    ["   /\\_/\\", "  ( o.o )", "   > ? <"],
    ["   /\\_/\\", "  ( -.- )", "   > ? <"],
    ["   /\\_/\\", "  ( o.o )", "   > ? <"],
  ],
  error: [
    ["   /\\_/\\", "  ( x.x )", "   > ! <"],
    ["   /\\_/\\", "  ( >.< )", "   > ! <"],
  ],
  success: [
    ["   /\\_/\\", "  ( ^.^ )", "   > v <"],
    ["   /\\_/\\", "  ( ^o^ )", "   > V <"],
    ["   /\\_/\\", "  ( ^.^ )", "   > v <"],
  ],
};

const STATE_COLORS = {
  idle: "textMuted",
  busy: "primary",
  thinking: "accent",
  error: "error",
  success: "success",
};

const STATE_LABELS = {
  idle: "idle",
  busy: "working",
  thinking: "thinking",
  error: "error",
  success: "done",
};

function element(tag, props, children = []) {
  const node = createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value !== undefined) setProp(node, key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) insert(node, child);
  }
  return node;
}

function text(props, children) {
  return element("text", props, children);
}

function box(props, children = []) {
  return element("box", props, children);
}

function PetBox(api) {
  const [petState, setPetState] = createSignal("idle");
  const [frame, setFrame] = createSignal(0);
  const [message, setMessage] = createSignal("");
  const theme = api.theme.current;

  const unsubStatus = api.event.on("session.status", (event) => {
    const statusType = event.properties.status.type;
    setPetState(statusType === "busy" || statusType === "retry" ? "busy" : "idle");
  });

  let thinkTimer = null;
  const unsubPrompt = api.event.on("tui.prompt.append", () => {
    setPetState("thinking");
    setMessage("Thinking...");
    if (thinkTimer) clearTimeout(thinkTimer);
    thinkTimer = setTimeout(() => {
      setPetState("idle");
      setMessage("Done!");
      thinkTimer = setTimeout(() => setMessage(""), 2000);
    }, 2000);
  });

  const unsubPart = api.event.on("message.part.updated", (event) => {
    const part = event.properties?.part;
    if (part?.type === "text" && part.text) setPetState("busy");
  });

  const unsubError = api.event.on("session.error", () => {
    setPetState("error");
    setMessage("Error");
  });

  const unsubIdle = api.event.on("session.idle", () => {
    setPetState("idle");
    setMessage("Done!");
  });

  const unsubCreated = api.event.on("session.created", () => {
    setPetState("idle");
    setMessage("Ready");
  });

  const unsubDeleted = api.event.on("session.deleted", () => {
    setPetState("idle");
    setMessage("Ended");
  });

  onCleanup(() => {
    unsubStatus();
    unsubPrompt();
    unsubPart();
    unsubError();
    unsubIdle();
    unsubCreated();
    unsubDeleted();
    if (thinkTimer) clearTimeout(thinkTimer);
  });

  const interval = setInterval(() => {
    setFrame((f) => (f + 1) % (FRAMES[petState()] || FRAMES.idle).length);
  }, 200);

  onCleanup(() => clearInterval(interval));

  const root = box(
    { border: { type: "none" }, padding: { top: 0, bottom: 0, left: 1, right: 1 } },
    []
  );

  createEffect(() => {
    const state = petState();
    const color = theme[STATE_COLORS[state]] || theme.textMuted;
    const frames = FRAMES[state] || FRAMES.idle;
    const line = frames[frame() % frames.length];
    const parts = [];
    for (const item of line) {
      parts.push(text({ fg: color }, [item]));
    }
    parts.push(text({ fg: theme.textMuted }, [STATE_LABELS[state] || "idle"]));
    const msg = message();
    if (msg) {
      parts.push(text({ fg: theme.textMuted, italic: true }, [msg.slice(0, 20)]));
    }
    insert(root, parts);
  });

  return root;
}

const tui = async (api, options, meta) => {
  console.log("[PET-PLUGIN] TUI CALLED, api keys:", Object.keys(api || {}));
  api.slots.register({
    slots: {
      sidebar_content(props) {
        return createComponent(PetBox, { api });
      },
    },
  });

  if (api.keymap?.registerLayer) {
    api.keymap.registerLayer({
      commands: [
        {
          namespace: "pet",
          name: "pet.status",
          title: "Pet Status",
          desc: "Show pet status and web URL",
          run: () => {
            api.ui.toast?.({
              title: "OpenCode Pet",
              message: "OpenCode Pet desktop app (tray icon: OpenCode Pet)",
              variant: "info",
              duration: 5000,
            });
          },
        },
        {
          namespace: "pet",
          name: "pet.open",
          title: "Open Pet on Desktop",
          desc: "Open the pet as a native desktop window",
          run: () => {
            const here = path.dirname(fileURLToPath(import.meta.url));
            const exe = path.join(here, "OpenCodePet.exe");
            if (fs.existsSync(exe)) {
              spawn(exe, [], { detached: true, stdio: "ignore", windowsHide: true })?.unref();
            } else {
              const script = path.join(here, "..", "desktop", "main.py");
              spawn("cmd", ["/c", "start", "", "python", "\"" + script + "\""], { detached: true, stdio: "ignore", windowsHide: true })?.unref();
            }
            api.ui.toast?.({
              title: "Pet",
              message: "Desktop pet opening...",
              variant: "info",
              duration: 2000,
            });
          },
        },
      ],
      bindings: [],
    });
  }
};

const plugin = {
  id: "local.pet.tui",
  tui,
};

export default plugin;
