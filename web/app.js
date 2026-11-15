const conversation = document.querySelector("#conversation");
const messagesElement = document.querySelector("#messages");
const welcome = document.querySelector("#welcome");
const threadList = document.querySelector("#thread-list");
const threadSearch = document.querySelector("#thread-search");
const threadLabel = document.querySelector("#active-thread-label");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const voiceButton = document.querySelector("#voice-button");
const inputHint = document.querySelector("#input-hint");
const newChatButton = document.querySelector("#new-chat");
const manageMemoriesButton = document.querySelector("#manage-memories");
const memoryDialog = document.querySelector("#memory-dialog");
const memorySearch = document.querySelector("#memory-search");
const memoryForm = document.querySelector("#memory-add-form");
const memoryInput = document.querySelector("#memory-input");
const memoryList = document.querySelector("#memory-list");
const memoryStatus = document.querySelector("#memory-status");

let activeThread = "";
let busy = false;
let threadSearchTimer;
let memorySearchTimer;
let speechRecognition = null;
let listening = false;
let speechBaseText = "";

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function threadName(threadId) {
  return threadId === "default"
    ? "Default conversation"
    : `Conversation ${threadId.slice(0, 8)}`;
}

function setActiveThread(threadId) {
  activeThread = threadId;
  localStorage.setItem("atmos-thread-id", threadId);
  threadLabel.textContent = threadName(threadId);
  for (const item of threadList.querySelectorAll(".thread-item")) {
    item.classList.toggle("active", item.dataset.threadId === threadId);
  }
}

function addMessage(
  role,
  text,
  { error = false, thinking = false, html = null } = {},
) {
  const row = document.createElement("article");
  row.className = `message ${role}${error ? " error" : ""}${thinking ? " thinking" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "Y" : "A";

  const content = document.createElement("div");
  content.className = "message-content";
  if (thinking) {
    content.append(document.createTextNode("Atmos is thinking"));
    const dots = document.createElement("span");
    dots.className = "thinking-dots";
    for (let i = 0; i < 3; i += 1) {
      dots.append(document.createElement("i"));
    }
    content.append(dots);
  } else if (role === "assistant" && typeof html === "string") {
    content.classList.add("markdown-body");
    content.innerHTML = html;
  } else {
    content.textContent = text;
  }

  row.append(avatar, content);
  messagesElement.append(row);
  welcome.hidden = messagesElement.children.length > 0;
  conversation.scrollTop = conversation.scrollHeight;
  return row;
}

function formatTraceValue(value) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? "";
}

function createActivityFeed() {
  const feed = document.createElement("details");
  feed.className = "activity-feed";
  const summary = document.createElement("summary");
  summary.textContent = "Agent activity";
  const entries = document.createElement("div");
  entries.className = "activity-entries";
  feed.append(summary, entries);
  messagesElement.append(feed);
  return { element: feed, entries, runs: new Map() };
}

function addActivityCard(feed, title, initial = "") {
  const card = document.createElement("article");
  card.className = "activity-card";
  const heading = document.createElement("div");
  heading.className = "activity-title";
  heading.textContent = title;
  const body = document.createElement("pre");
  body.className = "activity-output";
  body.textContent = initial;
  card.append(heading, body);
  feed.entries.append(card);
  conversation.scrollTop = conversation.scrollHeight;
  return { card, body };
}

function renderTraceEvent(feed, event) {
  const existing = event.run_id && feed.runs.get(event.run_id);
  if (event.type === "ai_start") {
    const entry = addActivityCard(feed, `AI message · ${event.name}`, "Generating…");
    entry.content = "";
    feed.runs.set(event.run_id, entry);
    return;
  }
  if (event.type === "ai_delta") {
    if (existing) {
      existing.content += event.content;
      existing.body.textContent = existing.content;
    }
    return;
  }
  if (event.type === "ai_message") {
    const entry = existing || addActivityCard(feed, `AI message · ${event.name}`);
    const content = event.content || formatTraceValue(event.raw_content);
    const calls = event.tool_calls?.length
      ? `\n\nTool calls:\n${formatTraceValue(event.tool_calls)}`
      : "";
    if (event.html && !calls) {
      entry.body.className = "activity-output activity-markdown markdown-body";
      entry.body.innerHTML = event.html;
    } else {
      entry.body.textContent = `${content}${calls}` || "(empty AI message)";
    }
    return;
  }
  if (event.type === "tool_start") {
    const entry = addActivityCard(feed, `Tool · ${event.name} · running`, `Input:\n${formatTraceValue(event.input)}`);
    feed.runs.set(event.run_id, entry);
    return;
  }
  if (event.type === "tool_end") {
    const entry = existing || addActivityCard(feed, `Tool · ${event.name}`);
    entry.card.querySelector(".activity-title").textContent = `Tool · ${event.name} · complete`;
    entry.body.textContent += `\n\nOutput:\n${formatTraceValue(event.output)}`;
    return;
  }
  if (event.type === "tool_error") {
    const entry = existing || addActivityCard(feed, `Tool · ${event.name}`);
    entry.card.classList.add("activity-error");
    entry.card.querySelector(".activity-title").textContent = `Tool · ${event.name} · failed`;
    entry.body.textContent += `\n\nError:\n${event.error}`;
    return;
  }
  if (event.type === "retry") {
    addActivityCard(
      feed,
      `Retry ${event.attempt}/${event.maximum}`,
      event.message,
    );
    return;
  }
  if (event.type === "progress") {
    const entry = addActivityCard(feed, "Progress", event.message);
    entry.card.classList.add("progress-card");
    return;
  }
  if (event.type === "custom") {
    addActivityCard(feed, `Agent event · ${event.name}`, formatTraceValue(event.data));
  }
}

function showMessages(messages) {
  messagesElement.replaceChildren();
  for (const message of messages) {
    if (message.role === "assistant" && message.events?.length) {
      const feed = createActivityFeed();
      for (const event of message.events) {
        renderTraceEvent(feed, event);
      }
    }
    addMessage(message.role, message.content, { html: message.html });
  }
  welcome.hidden = messages.length > 0;
}

async function streamChat(threadId, message, onEvent) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
    },
    body: JSON.stringify({ thread_id: threadId, message }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = null;
  let answerHtml = null;
  const consumeFrame = (frame) => {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = JSON.parse(data);
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "final") {
      answer = event.answer;
      answerHtml = event.html;
    }
    onEvent(event);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      consumeFrame(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
    }
    if (done) break;
  }
  if (buffer.trim()) consumeFrame(buffer);
  if (answer === null) throw new Error("The agent stream ended without a final answer.");
  return { answer, html: answerHtml };
}

async function loadThreads(query = threadSearch.value.trim()) {
  const search = query ? `?query=${encodeURIComponent(query)}` : "";
  const { threads, matches } = await request(`/api/threads${search}`);
  const firstMatch = new Map();
  for (const match of matches) {
    if (!firstMatch.has(match.thread_id)) firstMatch.set(match.thread_id, match);
  }
  threadList.replaceChildren();
  if (threads.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-threads";
    empty.textContent = query
      ? "No conversations match that search."
      : "Your conversations will appear here.";
    threadList.append(empty);
    return threads;
  }

  for (const threadId of threads) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thread-item";
    button.dataset.threadId = threadId;
    button.title = threadId;
    const icon = document.createElement("span");
    icon.className = "thread-icon";
    icon.textContent = "◷";
    const text = document.createElement("span");
    text.className = "thread-details";
    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = threadName(threadId);
    text.append(title);
    const match = firstMatch.get(threadId);
    if (match) {
      const snippet = document.createElement("span");
      snippet.className = "thread-match";
      snippet.textContent = `${match.role === "user" ? "You" : "Atmos"}: ${match.content}`;
      text.append(snippet);
    }
    button.append(icon, text);
    button.addEventListener("click", () => openThread(threadId));
    threadList.append(button);
  }
  setActiveThread(activeThread);
  return threads;
}

async function loadMemories(query = memorySearch.value.trim()) {
  memoryStatus.textContent = "Loading memories…";
  memoryList.replaceChildren();
  try {
    const search = query ? `?query=${encodeURIComponent(query)}` : "";
    const { memories } = await request(`/api/memories${search}`);
    memoryStatus.textContent = `${memories.length} ${memories.length === 1 ? "memory" : "memories"}`;
    if (!memories.length) {
      const empty = document.createElement("div");
      empty.className = "memory-empty";
      empty.textContent = query
        ? "No memories match that search."
        : "No saved memories yet.";
      memoryList.append(empty);
      return;
    }

    for (const memory of memories) {
      const item = document.createElement("article");
      item.className = "memory-item";
      const content = document.createElement("div");
      content.className = "memory-content";
      content.textContent = memory.content;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "memory-delete";
      remove.textContent = "Delete";
      remove.addEventListener("click", async () => {
        if (!window.confirm("Delete this saved memory?")) return;
        try {
          await request(`/api/memories/${memory.id}`, { method: "DELETE" });
          await loadMemories();
        } catch (error) {
          memoryStatus.textContent = error.message;
        }
      });
      item.append(content, remove);
      memoryList.append(item);
    }
  } catch (error) {
    memoryStatus.textContent = error.message;
  }
}

async function openThread(threadId) {
  setActiveThread(threadId);
  try {
    const data = await request(
      `/api/threads/${encodeURIComponent(threadId)}/messages?limit=200`,
    );
    showMessages(data.messages);
  } catch (error) {
    addMessage("assistant", error.message, { error: true });
  }
}

function startNewConversation() {
  setActiveThread(crypto.randomUUID());
  showMessages([]);
  messageInput.focus();
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (listening) speechRecognition?.stop();
  const message = messageInput.value.trim();
  if (!message || busy) return;

  busy = true;
  sendButton.disabled = true;
  messageInput.disabled = true;
  addMessage("user", message);
  const pending = addMessage("assistant", "", { thinking: true });
  const activity = createActivityFeed();
  messageInput.value = "";
  messageInput.style.height = "auto";

  try {
    const result = await streamChat(activeThread, message, (traceEvent) => {
      if (traceEvent.type !== "final") {
        pending.remove();
        renderTraceEvent(activity, traceEvent);
      }
    });
    pending.remove();
    if (!activity.entries.children.length) activity.element.remove();
    addMessage("assistant", result.answer, { html: result.html });
    await loadThreads();
  } catch (error) {
    pending.remove();
    if (!activity.entries.children.length) activity.element.remove();
    addMessage("assistant", error.message, { error: true });
  } finally {
    busy = false;
    sendButton.disabled = false;
    messageInput.disabled = false;
    messageInput.focus();
  }
});

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

function setListening(active, hint = "") {
  listening = active;
  voiceButton.classList.toggle("listening", active);
  voiceButton.setAttribute("aria-label", active ? "Stop voice dictation" : "Start voice dictation");
  voiceButton.title = active ? "Stop voice dictation" : "Start voice dictation";
  inputHint.textContent = hint || (active
    ? "Listening… Speak now, then tap the microphone to stop."
    : "Enter to send · Shift + Enter for a new line");
}

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  speechRecognition = new SpeechRecognition();
  speechRecognition.lang = navigator.language || "en-US";
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;

  speechRecognition.onstart = () => setListening(true);
  speechRecognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let index = 0; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript;
      if (event.results[index].isFinal) finalText += transcript;
      else interimText += transcript;
    }
    const prefix = speechBaseText.trim()
      ? `${speechBaseText.trimEnd()}${finalText || interimText ? " " : ""}`
      : "";
    messageInput.value = `${prefix}${finalText}${interimText}`;
    messageInput.dispatchEvent(new Event("input", { bubbles: true }));
  };
  speechRecognition.onerror = (event) => {
    const messages = {
      "not-allowed": "Microphone access was denied. Allow microphone access and try again.",
      "no-speech": "No speech detected. Tap the microphone to try again.",
      "audio-capture": "No microphone was found. Check your audio device.",
      "network": "Speech recognition needs a network connection in this browser.",
    };
    setListening(false, messages[event.error] || `Voice dictation error: ${event.error}.`);
  };
  speechRecognition.onend = () => setListening(false);

  voiceButton.addEventListener("click", () => {
    if (listening) {
      speechRecognition.stop();
      return;
    }
    speechBaseText = messageInput.value;
    try {
      speechRecognition.start();
    } catch (_error) {
      setListening(false, "Could not start voice dictation. Please try again.");
    }
  });
} else {
  voiceButton.disabled = true;
  voiceButton.title = "Voice dictation is not supported by this browser";
  inputHint.textContent = "Voice dictation is unavailable in this browser. Enter to send · Shift + Enter for a new line";
}

newChatButton.addEventListener("click", startNewConversation);

threadSearch.addEventListener("input", () => {
  window.clearTimeout(threadSearchTimer);
  threadSearchTimer = window.setTimeout(
    () => loadThreads(threadSearch.value.trim()),
    180,
  );
});

manageMemoriesButton.addEventListener("click", () => {
  memoryDialog.showModal();
  loadMemories();
});

document.querySelector("#close-memories").addEventListener("click", () => {
  memoryDialog.close();
});

memoryDialog.addEventListener("click", (event) => {
  if (event.target === memoryDialog) memoryDialog.close();
});

memorySearch.addEventListener("input", () => {
  window.clearTimeout(memorySearchTimer);
  memorySearchTimer = window.setTimeout(
    () => loadMemories(memorySearch.value.trim()),
    180,
  );
});

memoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = memoryInput.value.trim();
  if (!content) return;
  memoryStatus.textContent = "Saving…";
  try {
    await request("/api/memories", {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    memoryInput.value = "";
    memorySearch.value = "";
    await loadMemories();
  } catch (error) {
    memoryStatus.textContent = error.message;
  }
});

document.querySelector("#clear-thread").addEventListener("click", async () => {
  if (!threadList.querySelector(`[data-thread-id="${CSS.escape(activeThread)}"]`)) {
    startNewConversation();
    return;
  }
  if (!window.confirm("Clear this conversation's saved history?")) return;
  try {
    await request(`/api/threads/${encodeURIComponent(activeThread)}`, {
      method: "DELETE",
    });
    showMessages([]);
    await loadThreads();
    startNewConversation();
  } catch (error) {
    addMessage("assistant", error.message, { error: true });
  }
});

async function initialize() {
  try {
    const threads = await loadThreads();
    const remembered = localStorage.getItem("atmos-thread-id");
    const threadId = remembered || threads[0] || crypto.randomUUID();
    if (threads.includes(threadId) || !threads.length) {
      await openThread(threadId);
    } else {
      await openThread(threads[0]);
    }
  } catch (error) {
    welcome.hidden = true;
    addMessage(
      "assistant",
      `Could not connect to Atmos: ${error.message}. Check that the local server is running.`,
      { error: true },
    );
  }
}

initialize();
