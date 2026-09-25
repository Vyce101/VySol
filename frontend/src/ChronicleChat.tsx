import { ArrowRight, CaretRight, SlidersHorizontal, Stop } from "@phosphor-icons/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, jsonRequest, streamChronicleMessage, type ChatAppearance, type ChronicleMessage, type ChronicleSettings, type ChronicleStreamEvent } from "./api";
import { ChronicleMarkdown } from "./ChronicleMarkdown";
import { ChronicleSettingsDrawer } from "./ChronicleSettingsDrawer";

type ChatMessage = ChronicleMessage & { clientRequestId?: string; isLive?: boolean; activeThinking?: boolean };

type ChronicleChatProps = {
  visible: boolean;
  worldId: string;
  worldName: string;
  chronicleId: string;
  chronicleName: string;
  appearance?: ChatAppearance;
  visitKey?: number;
  onChronicleChanged?: (title: string) => void;
};

function requestId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (letter) => {
      const random = Math.floor(Math.random() * 16);
      const value = letter === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
}

export function ChronicleChat({ visible, worldId, worldName, chronicleId, chronicleName, appearance = "focused", visitKey = 0, onChronicleChanged }: ChronicleChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [settings, setSettings] = useState<ChronicleSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingError, setLoadingError] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [generation, setGeneration] = useState<{ requestId: string; active: boolean } | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [settingsError, setSettingsError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(() => new Set());
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const responseBufferRef = useRef("");
  const responseStartedAtRef = useRef<number | null>(null);
  const revealedCountRef = useRef(0);
  const revealTimerRef = useRef<number | undefined>(undefined);
  const settingsLoadedRef = useRef(false);
  const expandedThinkingRef = useRef(new Set<string>());
  const lastPersistedSettingsRef = useRef("");
  const loadedSessionRef = useRef<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const ignoredRequestsRef = useRef(new Set<string>());
  const streamCompletionRef = useRef<ChronicleMessage | null | undefined>(undefined);
  const saveTimerRef = useRef<number | undefined>(undefined);
  const settingsSaveQueue = useRef(Promise.resolve());
  const streamAbortRef = useRef<AbortController | null>(null);
  const localStreamRequestRef = useRef<string | null>(null);
  const generationRef = useRef<{ requestId: string; active: boolean } | null>(null);
  const responseSpeedRef = useRef(50);
  const chatSessionKey = `${chronicleId}:${visitKey}`;
  const draft = drafts[chronicleId] ?? "";

  function updateDraft(value: string) {
    setDrafts((current) => current[chronicleId] === value
      ? current
      : { ...current, [chronicleId]: value });
  }

  function replaceExpandedThinking(next: Set<string>) {
    expandedThinkingRef.current = next;
    setExpandedThinking(next);
  }

  const stopRevealTimer = useCallback(() => {
    if (revealTimerRef.current) window.clearInterval(revealTimerRef.current);
    revealTimerRef.current = undefined;
  }, []);

  const revealText = useCallback((id: string, value: string) => {
    setMessages((current) => current.map((message) => message.id === id ? { ...message, text: value } : message));
  }, []);

  const refreshMessages = useCallback(async () => {
    const result = await api<ChronicleMessage[]>(`/chronicles/${encodeURIComponent(chronicleId)}/messages`);
    const hydrated = result.map((message) => message.status === "streaming" && message.request_id
      ? { ...message, clientRequestId: message.request_id, isLive: true }
      : message);
    setMessages(hydrated);
    const activeMessage = hydrated.find((message) => message.status === "streaming");
    if (activeMessage) {
      if (activeMessage.streaming_speed != null) responseSpeedRef.current = activeMessage.streaming_speed;
      if (activeMessage.request_id && localStreamRequestRef.current !== activeMessage.request_id) {
        const activeGeneration = { requestId: activeMessage.request_id, active: true };
        generationRef.current = activeGeneration;
        setGeneration(activeGeneration);
      }
    } else if (!localStreamRequestRef.current) {
      generationRef.current = null;
      setGeneration(null);
    }
  }, [chronicleId]);

  async function persistSettings(snapshot: ChronicleSettings) {
    const snapshotKey = JSON.stringify(snapshot);
    if (snapshotKey === lastPersistedSettingsRef.current && !saveTimerRef.current) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = undefined;
    setSaveState("saving");
    const save = settingsSaveQueue.current.then(async () => {
      if (snapshotKey === lastPersistedSettingsRef.current) return;
      try {
        await api<ChronicleSettings>("/chronicle-settings", jsonRequest("PUT", snapshot));
        lastPersistedSettingsRef.current = snapshotKey;
        setSaveState("saved");
        setSettingsError("");
      } catch (reason) {
        setSaveState("error");
        setSettingsError(reason instanceof Error ? reason.message : "Settings could not be saved.");
        throw reason;
      }
    });
    settingsSaveQueue.current = save.then(() => undefined, () => undefined);
    await save;
  }

  useEffect(() => {
    if (!visible || !chronicleId || loadedSessionRef.current === chatSessionKey) return;
    let cancelled = false;
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    localStreamRequestRef.current = null;
    activeSessionRef.current = chatSessionKey;
    atBottomRef.current = true;
    setLoading(true);
    setLoadingError("");
    setStreamError("");
    setSettingsError("");
    setMessages([]);
    setSettings(null);
    setGeneration(null);
    generationRef.current = null;
    settingsLoadedRef.current = false;
    lastPersistedSettingsRef.current = "";
    replaceExpandedThinking(new Set());
    Promise.all([
      api<ChronicleMessage[]>(`/chronicles/${encodeURIComponent(chronicleId)}/messages`),
      api<ChronicleSettings>("/chronicle-settings"),
    ]).then(([history, savedSettings]) => {
      if (cancelled) return;
      loadedSessionRef.current = chatSessionKey;
      const hydrated = history.map((message) => message.status === "streaming" && message.request_id
        ? { ...message, clientRequestId: message.request_id, isLive: true }
        : message);
      setMessages(hydrated);
      setSettings(savedSettings);
      settingsLoadedRef.current = true;
      lastPersistedSettingsRef.current = JSON.stringify(savedSettings);
      const activeMessage = hydrated.find((message) => message.status === "streaming" && message.request_id);
      if (activeMessage?.request_id) {
        const activeGeneration = { requestId: activeMessage.request_id, active: true };
        generationRef.current = activeGeneration;
        setGeneration(activeGeneration);
        responseSpeedRef.current = activeMessage.streaming_speed ?? savedSettings.streaming_speed;
      }
    }).catch((reason: unknown) => {
      if (!cancelled) {
        loadedSessionRef.current = null;
        setLoadingError(reason instanceof Error ? reason.message : "This Chronicle could not be opened.");
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [visible, chatSessionKey, chronicleId]);

  const hasRemoteGeneration = messages.some((message) => message.status === "streaming");
  const hasUnattachedGeneration = messages.some((message) => message.status === "streaming" && message.request_id !== localStreamRequestRef.current);
  useEffect(() => {
    if (!visible || !hasRemoteGeneration || !hasUnattachedGeneration) return;
    const timer = window.setInterval(() => { void refreshMessages().catch(() => undefined); }, 900);
    return () => window.clearInterval(timer);
  }, [visible, hasRemoteGeneration, hasUnattachedGeneration, refreshMessages]);

  useEffect(() => {
    if (!settings) return;
    if (!settingsLoadedRef.current) return;
    const encoded = JSON.stringify(settings);
    if (encoded === lastPersistedSettingsRef.current) return;
    setSaveState("saving");
    saveTimerRef.current = window.setTimeout(() => { void persistSettings(settings).catch(() => undefined); }, 400);
    return () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current); };
  }, [settings]);

  useEffect(() => () => {
    stopRevealTimer();
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    streamAbortRef.current?.abort();
  }, [stopRevealTimer]);

  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript && atBottomRef.current) transcript.scrollTop = transcript.scrollHeight;
  }, [messages, loading]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxHeight = Number.parseFloat(window.getComputedStyle(textarea).maxHeight);
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
    if (!draft) textarea.scrollTop = 0;
  }, [draft, chronicleId, visible]);

  function updateLiveAssistant(request: string, update: (current: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => message.clientRequestId === request && message.role === "assistant" ? update(message) : message));
  }

  function finishGeneration(request: string, status: ChronicleMessage["status"], finalMessage?: ChronicleMessage) {
    stopRevealTimer();
    const answer = responseBufferRef.current;
    streamCompletionRef.current = undefined;
    const pendingId = `pending-${request}`;
    if (finalMessage && finalMessage.id !== pendingId && expandedThinkingRef.current.has(pendingId)) {
      const next = new Set(expandedThinkingRef.current);
      next.delete(pendingId);
      next.add(finalMessage.id);
      replaceExpandedThinking(next);
    }
    setMessages((current) => {
      const assistant = finalMessage ?? current.find((message) => message.clientRequestId === request && message.role === "assistant");
      const userMessage = current.find((message) => message.clientRequestId === request && message.role === "user");
      const kept = current.filter((message) => message.clientRequestId !== request);
      if (userMessage) kept.push(userMessage);
      if (assistant && (finalMessage || answer || assistant.thinking)) {
        const completedAssistant = { ...assistant, id: finalMessage?.id ?? assistant.id, text: finalMessage?.text ?? answer, status: finalMessage?.status ?? status, isLive: false, activeThinking: false };
        kept.push(completedAssistant);
      }
      return kept;
    });
    generationRef.current = null;
    if (localStreamRequestRef.current === request) localStreamRequestRef.current = null;
    setGeneration(null);
  }

  function onStreamEvent(request: string, event: ChronicleStreamEvent) {
    if (activeSessionRef.current !== chatSessionKey || generationRef.current?.requestId !== request || ignoredRequestsRef.current.has(request)) return;
    if (event.type === "user_message") {
      setMessages((current) => current.map((message) => message.clientRequestId === request && message.role === "user" ? { ...event.message, clientRequestId: request } : message));
      return;
    }
    if (event.type === "thinking_delta") {
      const pendingId = `pending-${request}`;
      replaceExpandedThinking(new Set(expandedThinkingRef.current).add(pendingId));
      updateLiveAssistant(request, (message) => ({ ...message, thinking: `${message.thinking ?? ""}${event.text}`, activeThinking: responseBufferRef.current.length === 0 }));
      return;
    }
    if (event.type === "answer_delta") {
      responseBufferRef.current += event.text;
      responseStartedAtRef.current ??= performance.now();
      updateLiveAssistant(request, (message) => ({ ...message, activeThinking: false }));
      const speed = responseSpeedRef.current;
      if (speed === 100) {
        revealedCountRef.current = responseBufferRef.current.length;
        revealText(`pending-${request}`, responseBufferRef.current);
      } else if (speed > 0 && !revealTimerRef.current) {
        revealTimerRef.current = window.setInterval(() => {
          const age = Math.max(0, performance.now() - (responseStartedAtRef.current ?? performance.now()));
          const target = Math.min(responseBufferRef.current.length, Math.floor(age * responseSpeedRef.current / 1000));
          if (target > revealedCountRef.current) {
            revealedCountRef.current = target;
            revealText(`pending-${request}`, responseBufferRef.current.slice(0, target));
          }
          const completed = streamCompletionRef.current;
          if (completed !== undefined && revealedCountRef.current >= responseBufferRef.current.length) {
            finishGeneration(request, completed?.status ?? "complete", completed ?? undefined);
            void refreshMessages().catch(() => undefined);
          }
        }, 20);
      }
      return;
    }
    if (event.type === "completed") {
      const completedMessage = event.message;
      streamCompletionRef.current = completedMessage;
      const speed = responseSpeedRef.current;
      if (completedMessage === null) {
        finishGeneration(request, responseBufferRef.current ? "partial" : "complete");
        void refreshMessages().catch(() => undefined);
      } else if (speed > 0 && speed < 100 && revealedCountRef.current < responseBufferRef.current.length) {
        if (!revealTimerRef.current) {
          revealTimerRef.current = window.setInterval(() => {
            const age = Math.max(0, performance.now() - (responseStartedAtRef.current ?? performance.now()));
            const target = Math.min(responseBufferRef.current.length, Math.floor(age * responseSpeedRef.current / 1000));
            if (target > revealedCountRef.current) {
              revealedCountRef.current = target;
              revealText(`pending-${request}`, responseBufferRef.current.slice(0, target));
            }
            if (revealedCountRef.current >= responseBufferRef.current.length) {
              finishGeneration(request, completedMessage.status, completedMessage);
              void refreshMessages().catch(() => undefined);
            }
          }, 20);
        }
      } else {
        finishGeneration(request, completedMessage.status, completedMessage);
        void refreshMessages().catch(() => undefined);
      }
      return;
    }
    if (event.type === "error") {
      setStreamError(event.message);
      finishGeneration(request, event.assistant?.status ?? (responseBufferRef.current ? "partial" : "error"), event.assistant ?? undefined);
      void refreshMessages().catch(() => undefined);
    }
  }

  async function sendMessage() {
    const text = draft.trim();
    if (!text || generationRef.current || hasRemoteGeneration) return;
    if (!settings?.key_id) {
      setStreamError("Choose an API connection in Settings before sending a message.");
      return;
    }
    const id = requestId();
    const timestamp = new Date().toISOString();
    responseBufferRef.current = "";
    responseStartedAtRef.current = null;
    revealedCountRef.current = 0;
    streamCompletionRef.current = undefined;
    responseSpeedRef.current = settings.streaming_speed;
    setStreamError("");
    updateDraft("");
    textareaRef.current?.focus({ preventScroll: true });
    atBottomRef.current = true;
    const user: ChatMessage = { id: `user-${id}`, role: "user", text, thinking: null, created_at: timestamp, status: "complete", clientRequestId: id };
    const assistant: ChatMessage = { id: `pending-${id}`, role: "assistant", text: "", thinking: null, created_at: timestamp, status: "complete", clientRequestId: id, isLive: true, activeThinking: false };
    setMessages((current) => [...current, user, assistant]);
    const activeGeneration = { requestId: id, active: true };
    generationRef.current = activeGeneration;
    localStreamRequestRef.current = id;
    setGeneration(activeGeneration);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      try {
        await persistSettings(settings);
      } catch {
        setStreamError("Settings could not be saved. Try again before sending your message.");
        updateDraft(text);
        setMessages((current) => current.filter((message) => message.clientRequestId !== id));
        generationRef.current = null;
        localStreamRequestRef.current = null;
        setGeneration(null);
        return;
      }
      await streamChronicleMessage(chronicleId, id, text, (event) => onStreamEvent(id, event), controller.signal);
      if (generationRef.current?.requestId === id && activeSessionRef.current === chatSessionKey) {
        finishGeneration(id, responseBufferRef.current ? "partial" : "complete");
        void refreshMessages().catch(() => undefined);
        onChronicleChanged?.(chronicleName);
      }
    } catch (reason) {
      if (controller.signal.aborted || activeSessionRef.current !== chatSessionKey) return;
      setStreamError(reason instanceof Error ? reason.message : "The response could not be completed.");
      finishGeneration(id, responseBufferRef.current ? "partial" : "error");
      void refreshMessages().catch(() => undefined);
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
    }
  }

  async function stopGeneration() {
    const active = generationRef.current;
    if (!active) return;
    if (streamCompletionRef.current !== undefined) {
      const completedMessage = streamCompletionRef.current;
      revealedCountRef.current = responseBufferRef.current.length;
      revealText(`pending-${active.requestId}`, responseBufferRef.current);
      finishGeneration(active.requestId, completedMessage?.status ?? "complete", completedMessage ?? undefined);
      void refreshMessages().catch(() => undefined);
      return;
    }
    try {
      const result = await api<{ stopped: boolean; status?: string; message?: ChronicleMessage | null }>(`/chronicles/${encodeURIComponent(chronicleId)}/generations/${encodeURIComponent(active.requestId)}/stop`, { method: "POST" });
      if (!result.stopped && result.status !== "stopped") return;
      ignoredRequestsRef.current.add(active.requestId);
      streamAbortRef.current?.abort();
      finishGeneration(active.requestId, result.message?.status ?? "stopped", result.message ?? undefined);
      void refreshMessages().catch(() => undefined);
    } catch (reason) {
      setStreamError(reason instanceof Error ? reason.message : "Generation could not be stopped.");
    }
  }

  const onSettingsChange = useCallback((next: ChronicleSettings) => setSettings(next), []);
  const canSend = draft.trim().length > 0 && !generation && !hasRemoteGeneration;

  return (
    <section className={`view chronicle-chat-view ${appearance === "full_overlay" ? "is-full-overlay" : ""} ${visible ? "is-visible" : ""}`} aria-hidden={!visible} inert={!visible}>
      <div className="chronicle-chat-shell">
        <header className="chronicle-chat-title">
          <h1>{worldName}</h1>
          <div className="chronicle-title-divider"><span aria-hidden="true" /><h2>{chronicleName}</h2><span aria-hidden="true" /></div>
        </header>
        <div className="chronicle-transcript" ref={transcriptRef} onScroll={(event) => { const element = event.currentTarget; atBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72; }} aria-label="Chronicle messages" aria-live="off">
          {loading && <p className="chronicle-chat-loading" role="status"><span>Loading messages…</span></p>}
          {loadingError && <p className="chronicle-chat-error" role="alert">{loadingError}</p>}
          {!loading && !loadingError && messages.map((message) => {
            const isUser = message.role === "user";
            const expanded = expandedThinking.has(message.id);
            const thinkingText = message.thinking ?? "";
            const activeThinking = Boolean((message.activeThinking && generation?.requestId === message.clientRequestId) || (message.status === "streaming" && !message.text));
            return (
              <article className={`chronicle-message ${isUser ? "is-user" : "is-assistant"}`} key={message.id}>
                {!isUser && thinkingText && <section className={`chronicle-thinking ${expanded ? "is-expanded" : ""}`}>
                  <button type="button" className={`chronicle-thinking-trigger ${activeThinking ? "is-active" : ""}`} aria-expanded={expanded} aria-controls={`thinking-${message.id}`} onClick={() => { const next = new Set(expandedThinkingRef.current); if (next.has(message.id)) next.delete(message.id); else next.add(message.id); replaceExpandedThinking(next); }}>
                    <span>{activeThinking ? "Thinking…" : "Thinking"}</span><CaretRightSmall />
                  </button>
                  <div className="chronicle-thinking-panel" id={`thinking-${message.id}`} aria-hidden={!expanded} inert={!expanded}>
                    <div className="chronicle-thinking-copy"><ChronicleMarkdown text={thinkingText} /></div>
                  </div>
                </section>}
                {message.text && <div className="chronicle-message-copy"><ChronicleMarkdown text={message.text} /></div>}
              </article>
            );
          })}
        </div>
        <div className="chronicle-composer-area">
          {streamError && <p className="chronicle-chat-error" role="alert">{streamError}</p>}
          {hasRemoteGeneration && !generation && <p className="chronicle-chat-status" role="status">A response is still being generated.</p>}
          <div className="chronicle-composer">
            <textarea ref={textareaRef} rows={1} value={draft} onChange={(event) => updateDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !generationRef.current && !hasRemoteGeneration) { event.preventDefault(); void sendMessage(); } }} placeholder="What do you do?" aria-label="What do you do?" />
            <div className="chronicle-composer-actions">
              <button type="button" className={`chronicle-settings-inline-trigger ${settingsOpen ? "is-active" : ""}`} aria-label="Open Settings" aria-pressed={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}><SlidersHorizontal size={19} /></button>
              {generation ? <button type="button" className="chronicle-send-button is-stop" aria-label="Stop response" onClick={() => void stopGeneration()}><Stop size={19} weight="fill" /></button> : <button type="button" className={`chronicle-send-button ${draft.trim() ? "has-text" : ""}`} aria-label="Send message" onClick={() => void sendMessage()} disabled={!canSend}><ArrowRight size={20} /></button>}
            </div>
          </div>
        </div>
      </div>
      <ChronicleSettingsDrawer open={settingsOpen} settings={settings} onSettingsChange={onSettingsChange} saveState={saveState} saveError={settingsError} onClose={() => setSettingsOpen(false)} />
    </section>
  );
}

function CaretRightSmall() {
  return <CaretRight className="chronicle-thinking-chevron" size={16} aria-hidden="true" />;
}
