"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, isAbort } from "@/lib/api";
import {
  describeChatFailure,
  describeLoadFailure,
  type ChatFailure,
} from "@/lib/errors";
import {
  readStoredLLMMode,
  readStoredSessionId,
  storeLLMMode,
  storeSessionId,
} from "@/lib/preferences";
import type {
  ActivityEvent,
  Artifact,
  ChatMetrics,
  LLMMode,
  Message,
  Session,
  Source,
} from "@/types";

/** Local view of one conversation message. */
export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  artifact: Artifact | null;
  sources: Source[];
  metrics: ChatMetrics;
  /** True while the message exists only in the browser (not yet persisted). */
  pending: boolean;
};

export type ErrorScope = "sessions" | "messages" | "chat";

export type WorkspaceError = ChatFailure & { scope: ErrorScope };

export type WorkspaceStatus =
  | "initialising"
  | "loading-messages"
  | "sending"
  | "ready";

export type ArtifactView = { artifact: Artifact; messageId: string } | null;

/**
 * A turn this browser started and has not folded back into loaded history.
 *
 * It is keyed by the session that owns it, so a request keeps running and keeps
 * collecting its own progress while the reader is looking at another session.
 */
type SessionTurn = {
  phase: "running" | "settled" | "failed";
  /** The submitted message, shown until the persisted row replaces it. */
  optimistic: ChatMessage;
  /** The persisted pair once the turn is over; empty while it is running. */
  rows: ChatMessage[];
  activity: ActivityEvent[];
  startedAt: number;
  controller: AbortController;
  error: WorkspaceError | null;
};

const DEFAULT_LLM_MODE: LLMMode = "ollama";

const NO_ACTIVITY: ActivityEvent[] = [];

function toChatMessage(message: Message, extra?: Partial<ChatMessage>): ChatMessage {
  return {
    id: message.id,
    role: message.role === "user" ? "user" : "assistant",
    content: message.content,
    artifact: message.artifact ?? null,
    sources: [],
    metrics: {},
    pending: false,
    ...extra,
  };
}

/** System rows are never conversation content, so they are never rendered. */
function isConversationMessage(message: Message): boolean {
  return message.role === "user" || message.role === "assistant";
}

/** Rows the browser has that the loaded history does not show yet. */
function withoutDuplicates(
  loaded: ChatMessage[],
  rows: ChatMessage[],
): ChatMessage[] {
  const known = new Set(loaded.map((message) => message.id));
  return rows.filter((message) => !known.has(message.id));
}

export type Workspace = {
  sessions: Session[];
  selectedSessionId: string | null;
  selectedSession: Session | null;
  messages: ChatMessage[];
  artifactView: ArtifactView;
  llmMode: LLMMode;
  status: WorkspaceStatus;
  activity: ActivityEvent[];
  /** When the running turn started, so the elapsed timer survives a switch. */
  activityStartedAt: number | null;
  error: WorkspaceError | null;
  draft: string;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => void;
  send: (text: string) => Promise<void>;
  cancel: () => void;
  retry: () => void;
  refresh: () => void;
  setLLMMode: (mode: LLMMode) => void;
  setDraft: (text: string) => void;
  openArtifact: (messageId: string) => void;
  closeArtifact: () => void;
  dismissError: () => void;
};

/**
 * All workspace state lives here; components render it and call its actions.
 *
 * The backend database stays authoritative for conversation data: messages are
 * loaded per session, a turn is reconciled with the persisted rows the backend
 * returns, and nothing is cached between sessions.
 *
 * An in-flight turn is the exception: it exists before the database does, so it
 * is stored per session rather than tied to the selection. Switching sessions
 * changes what is displayed, never what is allowed to keep running.
 */
export function useWorkspace(): Workspace {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turns, setTurns] = useState<Record<string, SessionTurn>>({});
  const [artifactView, setArtifactView] = useState<ArtifactView>(null);
  const [llmMode, setLLMModeState] = useState<LLMMode>(DEFAULT_LLM_MODE);
  const [loadedStatus, setLoadedStatus] = useState<WorkspaceStatus>("initialising");
  const [error, setError] = useState<WorkspaceError | null>(null);
  const [draft, setDraft] = useState("");

  /** Bumped on every selection change so a late load cannot leak in. */
  const selectionRef = useRef(0);
  /** The session on screen, so a background turn never writes into another one. */
  const selectedIdRef = useRef<string | null>(null);
  /** Mirrors `turns` for callbacks, which must not read stale state. */
  const turnsRef = useRef<Record<string, SessionTurn>>({});

  const writeTurns = useCallback((next: Record<string, SessionTurn>) => {
    turnsRef.current = next;
    setTurns(next);
  }, []);

  /** Update one session's turn; returning `null` from `update` drops it. */
  const mutateTurn = useCallback(
    (
      sessionId: string,
      update: (current: SessionTurn | undefined) => SessionTurn | null,
    ) => {
      const current = turnsRef.current;
      const next = update(current[sessionId]);
      if (!next && !current[sessionId]) return;
      const copy = { ...current };
      if (next) copy[sessionId] = next;
      else delete copy[sessionId];
      writeTurns(copy);
    },
    [writeTurns],
  );

  /**
   * Hand a finished turn's rows to the loaded conversation. Only ever called for
   * the session on screen, which is the only one whose rows are held in state.
   */
  const foldTurnRows = useCallback(
    (sessionId: string) => {
      const turn = turnsRef.current[sessionId];
      if (!turn || turn.phase === "running") return;
      const rows = turn.rows;
      mutateTurn(sessionId, () => null);
      if (rows.length === 0) return;
      setMessages((current) => {
        const extra = withoutDuplicates(current, rows);
        return extra.length === 0 ? current : [...current, ...extra];
      });
    },
    [mutateTurn],
  );

  const loadSessions = useCallback(async (restore: boolean) => {
    try {
      const listed = await api.listSessions();
      let available = listed;
      if (listed.length === 0) {
        // A fresh workspace starts usable: the first session is created through
        // the same API the New Chat button uses.
        available = [await api.createSession(), ...listed];
      }
      setSessions(available);
      const stored = restore ? readStoredSessionId() : null;
      const target =
        stored && available.some((session) => session.id === stored)
          ? stored
          : (available[0]?.id ?? null);
      setSelectedSessionId(target);
      setError(null);
    } catch (cause) {
      setError({ ...describeLoadFailure(cause, "Sessions could not be loaded."), scope: "sessions" });
    } finally {
      setLoadedStatus("ready");
    }
  }, []);

  const refresh = useCallback(() => {
    setLoadedStatus("initialising");
    setError(null);
    void loadSessions(true);
  }, [loadSessions]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      // The stored mode is read after mount so the server render and the first
      // client render stay identical.
      const stored = readStoredLLMMode();
      if (stored && !cancelled) setLLMModeState(stored);

      try {
        await api.getHealth();
      } catch (cause) {
        if (cancelled) return;
        setError({
          ...describeLoadFailure(cause, "The backend is not reachable."),
          scope: "sessions",
        });
        setLoadedStatus("ready");
        return;
      }
      if (cancelled) return;
      await loadSessions(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [loadSessions]);

  // Switching sessions replaces the loaded conversation instead of appending to
  // the previous one. Resetting on the new selection is done during render,
  // which is how React handles state that is derived from a changed prop. A
  // turn in flight is deliberately left alone: it belongs to its session, not
  // to the selection, and the derivation below puts it back on screen.
  const [renderedSessionId, setRenderedSessionId] = useState<string | null>(null);
  if (renderedSessionId !== selectedSessionId) {
    setRenderedSessionId(selectedSessionId);
    setMessages([]);
    setArtifactView(null);
    setLoadedStatus(selectedSessionId ? "loading-messages" : "ready");
  }

  useEffect(() => {
    const token = ++selectionRef.current;
    selectedIdRef.current = selectedSessionId;
    if (!selectedSessionId) return;

    api
      .listMessages(selectedSessionId)
      .then((loaded) => {
        if (token !== selectionRef.current) return;
        const rows = loaded
          .filter(isConversationMessage)
          .map((message) => toChatMessage(message));
        setMessages(rows);
        setError(null);
        // The database now holds a settled turn's rows, so the browser copy of
        // them is no longer needed.
        const turn = turnsRef.current[selectedSessionId];
        if (turn && turn.phase !== "running" && turn.rows.length > 0) {
          const missing = withoutDuplicates(rows, turn.rows);
          if (missing.length === 0) mutateTurn(selectedSessionId, () => null);
        }
      })
      .catch((cause: unknown) => {
        if (token !== selectionRef.current) return;
        setMessages([]);
        setError({
          ...describeLoadFailure(cause, "Messages could not be loaded."),
          scope: "messages",
        });
      })
      .finally(() => {
        if (token === selectionRef.current) setLoadedStatus("ready");
      });
  }, [mutateTurn, selectedSessionId]);

  useEffect(() => {
    // Only a real selection is remembered: writing the initial null would erase
    // the stored preference before the bootstrap has read it.
    if (selectedSessionId) storeSessionId(selectedSessionId);
  }, [selectedSessionId]);

  const setLLMMode = useCallback((mode: LLMMode) => {
    setLLMModeState(mode);
    storeLLMMode(mode);
  }, []);

  const createSession = useCallback(async () => {
    setError(null);
    try {
      const session = await api.createSession();
      setSessions((current) => [session, ...current.filter((item) => item.id !== session.id)]);
      setSelectedSessionId(session.id);
    } catch (cause) {
      setError({
        ...describeLoadFailure(cause, "The session could not be created."),
        scope: "sessions",
      });
    }
  }, []);

  const selectSession = useCallback((sessionId: string) => {
    setSelectedSessionId((current) => (current === sessionId ? current : sessionId));
  }, []);

  const refreshSessionsQuietly = useCallback(async () => {
    // The backend renames an untitled session and reorders by activity. A
    // failure here must not undo a turn that already succeeded and persisted.
    try {
      setSessions(await api.listSessions());
    } catch {
      // Keep the list this browser already has.
    }
  }, []);

  const send = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      // The session that owns this turn from here on. It is captured now and
      // never re-read, because the reader may switch sessions while the model
      // is working.
      const sessionId = selectedSessionId;
      if (!text || !sessionId) return;
      // One live request per session; another session may run its own.
      if (turnsRef.current[sessionId]?.phase === "running") return;

      const mode = llmMode;
      const optimistic: ChatMessage = {
        id: `pending-${Date.now()}`,
        role: "user",
        content: text,
        artifact: null,
        sources: [],
        metrics: {},
        pending: true,
      };
      const controller = new AbortController();
      setError(null);
      setDraft("");
      foldTurnRows(sessionId);
      mutateTurn(sessionId, () => ({
        phase: "running",
        optimistic,
        rows: [],
        activity: [],
        startedAt: Date.now(),
        controller,
        error: null,
      }));

      try {
        const response = await api.streamChat(
          { session_id: sessionId, message: text, llm_mode: mode },
          (event) => {
            // Progress belongs to this session whether or not it is on screen.
            if (event.event === "activity") {
              mutateTurn(sessionId, (turn) =>
                turn ? { ...turn, activity: [...turn.activity, event.data] } : null,
              );
              return;
            }
            if (event.event === "artifact_ready" && selectedIdRef.current === sessionId) {
              // The viewer is part of the session that asked for the artifact.
              setArtifactView({ artifact: event.data, messageId: optimistic.id });
            }
          },
          controller.signal,
        );

        const settled = [
          toChatMessage(response.user_message),
          toChatMessage(response.message, {
            sources: response.sources ?? [],
            metrics: response.metrics ?? {},
          }),
        ];
        const onScreen = selectedIdRef.current === sessionId;
        // Written to the session that made the request. If another one is on
        // screen, these rows stay with their own session and are never merged
        // into the conversation the reader is looking at. They are retired by the
        // next load of that session, which reads them from the database.
        mutateTurn(sessionId, (turn) =>
          turn ? { ...turn, phase: "settled", rows: settled, activity: [] } : null,
        );
        if (onScreen) {
          setArtifactView(
            response.artifact
              ? { artifact: response.artifact, messageId: response.message.id }
              : null,
          );
        }
        await refreshSessionsQuietly();
      } catch (cause) {
        if (isAbort(cause)) {
          // Stopped on purpose: nothing persisted, and the composer only gives
          // the text back for the session it was written into.
          mutateTurn(sessionId, () => null);
          if (selectedIdRef.current === sessionId) setDraft(text);
          return;
        }
        // The failure belongs to its own session, so a reader of a different
        // session is never told their conversation failed. The turn was not
        // persisted, so it can be retried without duplicating it in the history.
        mutateTurn(sessionId, (turn) =>
          turn
            ? {
                ...turn,
                phase: "failed",
                rows: [],
                activity: [],
                error: { ...describeChatFailure(cause, mode), scope: "chat" },
              }
            : null,
        );
        if (selectedIdRef.current === sessionId) setDraft(text);
      }
    },
    [foldTurnRows, llmMode, mutateTurn, refreshSessionsQuietly, selectedSessionId],
  );

  const cancel = useCallback(() => {
    const sessionId = selectedIdRef.current;
    if (!sessionId) return;
    const turn = turnsRef.current[sessionId];
    if (turn?.phase === "running") turn.controller.abort();
  }, []);

  const retry = useCallback(() => {
    const sessionId = selectedIdRef.current;
    const failed = sessionId ? turnsRef.current[sessionId] : undefined;
    const text =
      draft.trim() || (failed?.phase === "failed" ? failed.optimistic.content : "");
    setError(null);
    if (text) void send(text);
  }, [draft, send]);

  const openArtifact = useCallback(
    (messageId: string) => {
      const message = messages.find((item) => item.id === messageId);
      if (message?.artifact) setArtifactView({ artifact: message.artifact, messageId });
    },
    [messages],
  );

  const closeArtifact = useCallback(() => setArtifactView(null), []);

  const dismissError = useCallback(() => {
    setError(null);
    const sessionId = selectedIdRef.current;
    if (sessionId && turnsRef.current[sessionId]?.error) {
      mutateTurn(sessionId, () => null);
    }
  }, [mutateTurn]);

  const selectedSession =
    sessions.find((session) => session.id === selectedSessionId) ?? null;

  // The selection decides what is displayed; the session's own turn, if any, is
  // layered on top of the rows loaded for it.
  const turn = selectedSessionId ? turns[selectedSessionId] : undefined;
  const running = turn?.phase === "running" ? turn : null;
  const visibleMessages = useMemo(() => {
    if (!turn) return messages;
    if (turn.phase === "running") return [...messages, turn.optimistic];
    const extra = withoutDuplicates(messages, turn.rows);
    return extra.length === 0 ? messages : [...messages, ...extra];
  }, [messages, turn]);

  return {
    sessions,
    selectedSessionId,
    selectedSession,
    messages: visibleMessages,
    artifactView,
    llmMode,
    status: running ? "sending" : loadedStatus,
    activity: running?.activity ?? NO_ACTIVITY,
    activityStartedAt: running?.startedAt ?? null,
    error: turn?.error ?? error,
    draft,
    createSession,
    selectSession,
    send,
    cancel,
    retry,
    refresh,
    setLLMMode,
    setDraft,
    openArtifact,
    closeArtifact,
    dismissError,
  };
}
