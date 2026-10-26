"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, ApiError, createRun, getRun } from "./api";
import { mergeEvent } from "./status";
import { EVENT_TYPES, TERMINAL, type RunEvent, type RunMode, type RunSnapshot } from "./types";

export type Connection = "idle" | "connecting" | "streaming" | "closed" | "lost";

export function useRun() {
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [connection, setConnection] = useState<Connection>("idle");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const source = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    source.current?.close();
    source.current = null;
  }, []);

  const attach = useCallback(
    (id: string) => {
      close();
      setConnection("connecting");
      const es = new EventSource(`${API_URL}/api/runs/${id}/events`);
      source.current = es;
      const onEvent = async (msg: MessageEvent) => {
        const ev = JSON.parse(msg.data) as RunEvent;
        setConnection("streaming");
        setEvents((prev) => mergeEvent(prev, ev));
        if (TERMINAL.includes(ev.type)) {
          es.close();
          setConnection("closed");
          try {
            setSnapshot(await getRun(id));
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          }
        }
      };
      for (const t of EVENT_TYPES) es.addEventListener(t, (e) => void onEvent(e as MessageEvent));
      es.onerror = () => {
        // EventSource retries on its own (resuming via Last-Event-ID) unless it was closed.
        if (es.readyState === EventSource.CLOSED) setConnection("lost");
      };
    },
    [close],
  );

  const start = useCallback(
    async (question: string, mode: RunMode) => {
      setSubmitting(true);
      setError(null);
      try {
        const { id } = await createRun(question, mode);
        setRunId(id);
        setEvents([]);
        setSnapshot(null);
        attach(id);
        return id;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [attach],
  );

  /** Open a past run: stream replays every stored event, then closes. */
  const open = useCallback(
    async (id: string) => {
      setError(null);
      setRunId(id);
      setEvents([]);
      setSnapshot(null);
      try {
        setSnapshot(await getRun(id));
        attach(id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [attach],
  );

  useEffect(() => close, [close]);

  return { runId, events, snapshot, connection, error, submitting, start, open };
}
