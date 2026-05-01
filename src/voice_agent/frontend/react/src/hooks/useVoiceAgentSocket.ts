import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { appConfig } from "../utils/config";
import {
  formatPhaseLabel,
  formatTokens,
  generateCallId,
} from "../utils/utils";
import type {
  CallDetail,
  CallLog,
  CallTurn,
  ConnectionState,
  InternalEvent,
  LiveCallState,
  LiveClientCommand,
  LiveMessage,
  LiveServerEvent,
  LogEntry,
  TimelineEntry,
} from "../types/voice-agent";

function makeTimelineEntry(entry: Omit<TimelineEntry, "id">): TimelineEntry {
  return {
    id: `${entry.kind}-${entry.timestamp}-${Math.random().toString(16).slice(2, 8)}`,
    ...entry,
  };
}

function roleFromTurn(role: string): LiveMessage["role"] {
  if (role === "assistant" || role === "user" || role === "system") {
    return role;
  }
  return "system";
}

function toLiveMessage(callId: string, turn: CallTurn, index: number): LiveMessage {
  return {
    id: `${callId}:db:${index}`,
    role: roleFromTurn(turn.role),
    content: turn.content,
    created_at: turn.created_at,
  };
}

function toLogEntry(callId: string, log: CallLog, index: number): LogEntry {
  return {
    id: `${callId}:log:${index}:${log.timestamp}`,
    level: log.level,
    message: log.message,
    timestamp: log.timestamp,
    details: log.details,
  };
}

function isSameMessage(left: LiveMessage, right: LiveMessage): boolean {
  return (
    left.role === right.role &&
    left.content === right.content &&
    (left.created_at || "") === (right.created_at || "")
  );
}

function isSameLog(left: LogEntry, right: LogEntry): boolean {
  return (
    left.level === right.level &&
    left.message === right.message &&
    left.timestamp === right.timestamp
  );
}

export interface VoiceAgentSocketState {
  callId: string;
  connectionState: ConnectionState;
  session: LiveCallState | null;
  transcript: LiveMessage[];
  streamingMessage: LiveMessage | null;
  isStreaming: boolean;
  currentNode: string | null;
  lastError: string | null;
  timeline: TimelineEntry[];
  logs: LogEntry[];
  connect: (callId?: string) => void;
  disconnect: () => void;
  sendUserMessage: (text: string) => void;
  cancelActiveResponse: () => void;
  resetToNewCall: () => string;
}

export function useVoiceAgentSocket(): VoiceAgentSocketState {
  const [callId, setCallId] = useState<string>(generateCallId());
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [session, setSession] = useState<LiveCallState | null>(null);
  const [transcript, setTranscript] = useState<LiveMessage[]>([]);
  const [streamingMessage, setStreamingMessage] = useState<LiveMessage | null>(null);
  const [currentNode, setCurrentNode] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const manualCloseRef = useRef(false);
  const reconnectTimerRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const callIdRef = useRef(callId);
  const transcriptSyncIdRef = useRef(0);

  const pushTimeline = useCallback((entry: Omit<TimelineEntry, "id">) => {
    setTimeline((current) => [...current.slice(-149), makeTimelineEntry(entry)]);
  }, []);

  const pushLog = useCallback((entry: Omit<LogEntry, "id">) => {
    setLogs((current) => [
      ...current.slice(-199),
      {
        id: `${entry.level}-${entry.timestamp}-${Math.random().toString(16).slice(2, 8)}`,
        ...entry,
      },
    ]);
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const clearPingInterval = useCallback(() => {
    if (pingIntervalRef.current !== null) {
      window.clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  const sendCommand = useCallback((command: LiveClientCommand) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    socket.send(JSON.stringify(command));
  }, []);

  const resetSessionState = useCallback((nextCallId: string) => {
    transcriptSyncIdRef.current += 1;
    setCallId(nextCallId);
    callIdRef.current = nextCallId;
    setSession(null);
    setTranscript([]);
    setStreamingMessage(null);
    setCurrentNode(null);
    setTimeline([]);
    setLogs([]);
    setLastError(null);
  }, []);

  const appendTranscriptMessage = useCallback((message: LiveMessage) => {
    setTranscript((current) => {
      if (current.some((existing) => isSameMessage(existing, message))) {
        return current;
      }
      return [...current, message];
    });
  }, []);

  const syncPersistedCallData = useCallback(
    async (targetCallId: string) => {
      const normalizedCallId = targetCallId.trim();
      if (!normalizedCallId) {
        return;
      }

      const syncId = ++transcriptSyncIdRef.current;

      try {
        const response = await fetch(
          `${appConfig.apiBaseUrl}/calls/${encodeURIComponent(normalizedCallId)}`,
        );

        if (response.status === 404) {
          return;
        }

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const detail = (await response.json()) as CallDetail;
        if (syncId !== transcriptSyncIdRef.current || callIdRef.current !== normalizedCallId) {
          return;
        }

        setTranscript(detail.turns.map((turn, index) => toLiveMessage(normalizedCallId, turn, index)));
        setLogs((current) => {
          const merged = [...current];
          for (const entry of detail.logs.map((log, index) => toLogEntry(normalizedCallId, log, index))) {
            if (merged.some((existing) => isSameLog(existing, entry))) {
              continue;
            }
            merged.push(entry);
          }
          return merged.slice(-200);
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to refresh persisted call data.";
        pushLog({
          level: "warning",
          message: "Call history sync failed.",
          timestamp: new Date().toISOString(),
          details: {
            call_id: normalizedCallId,
            error: message,
          },
        });
      }
    },
    [pushLog],
  );

  const openSocket = useCallback(
    (targetCallId: string, reconnecting: boolean) => {
      clearReconnectTimer();
      clearPingInterval();
      setConnectionState(reconnecting ? "reconnecting" : "connecting");

      const url = `${appConfig.wsBaseUrl}/${encodeURIComponent(targetCallId)}`;
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        reconnectAttemptRef.current = 0;
        setConnectionState("connected");
        pushLog({
          level: "info",
          message: reconnecting ? "WebSocket reconnected." : "WebSocket connected.",
          timestamp: new Date().toISOString(),
        });
        pingIntervalRef.current = window.setInterval(() => {
          sendCommand({
            type: "ping",
            timestamp: Date.now(),
          });
        }, 15000);
      };

      socket.onmessage = (message) => {
        let event: LiveServerEvent;
        try {
          event = JSON.parse(message.data) as LiveServerEvent;
        } catch {
          pushLog({
            level: "warning",
            message: "Received a non-JSON websocket frame.",
            timestamp: new Date().toISOString(),
          });
          return;
        }

        switch (event.type) {
          case "session.ready": {
            setSession(event.state);
            setCurrentNode(event.state.current_node || null);
            void syncPersistedCallData(event.call_id);
            pushTimeline({
              kind: "system",
              title: "Session ready",
              description: `Connected to call ${event.call_id}.`,
              timestamp: event.timestamp,
            });
            return;
          }

          case "state.snapshot": {
            setSession(event.state);
            setCurrentNode(event.state.current_node || null);
            return;
          }

          case "user.message": {
            appendTranscriptMessage(event.message);
            void syncPersistedCallData(callIdRef.current);
            pushTimeline({
              kind: "user",
              title: "User message",
              description: event.message.content,
              timestamp: event.timestamp,
              tone: "accent",
            });
            return;
          }

          case "assistant.response.started": {
            setStreamingMessage({
              id: `${callIdRef.current}:stream:${event.response_id}`,
              role: "assistant",
              content: "",
              response_id: event.response_id,
              created_at: event.timestamp,
            });
            pushTimeline({
              kind: "system",
              title: "Assistant responding",
              description: event.trigger ? `Trigger: ${event.trigger}` : undefined,
              timestamp: event.timestamp,
            });
            return;
          }

          case "assistant.response.delta": {
            setStreamingMessage((current) => {
              if (!current || current.response_id !== event.response_id) {
                return {
                  id: `${callIdRef.current}:stream:${event.response_id}`,
                  role: "assistant",
                  content: event.delta,
                  response_id: event.response_id,
                  created_at: event.timestamp,
                };
              }
              return {
                ...current,
                content: `${current.content}${event.delta}`,
              };
            });
            return;
          }

          case "assistant.response.completed": {
            setStreamingMessage(null);
            setSession(event.state);
            setCurrentNode(event.state.current_node || null);
            appendTranscriptMessage(event.message);
            void syncPersistedCallData(callIdRef.current);
            pushTimeline({
              kind: "assistant",
              title: "Assistant response",
              description: event.message.content,
              timestamp: event.timestamp,
              meta: [
                event.metrics.total_latency_s ? `Latency ${event.metrics.total_latency_s.toFixed(2)}s` : "",
                event.metrics.ttft_s ? `TTFT ${event.metrics.ttft_s.toFixed(2)}s` : "",
                event.metrics.total_tokens ? `${formatTokens(event.metrics.total_tokens)} tokens` : "",
              ].filter(Boolean),
            });
            return;
          }

          case "assistant.response.cancelled": {
            setStreamingMessage(null);
            pushTimeline({
              kind: "system",
              title: "Response cancelled",
              description: formatPhaseLabel(event.reason),
              timestamp: event.timestamp,
              tone: "warning",
            });
            return;
          }

          case "phase.changed": {
            setSession((current) =>
              current
                ? {
                    ...current,
                    phase: event.phase,
                    assistant_phase: event.assistant_phase,
                    next_action: event.next_action,
                    current_node: event.current_node,
                  }
                : current,
            );
            setCurrentNode(event.current_node || null);
            pushTimeline({
              kind: "phase",
              title: "Phase updated",
              description: [
                event.assistant_phase ? formatPhaseLabel(event.assistant_phase) : "",
                event.next_action ? `next ${formatPhaseLabel(event.next_action)}` : "",
              ]
                .filter(Boolean)
                .join(" • "),
              timestamp: event.timestamp,
            });
            return;
          }

          case "appointment.updated": {
            setSession((current) =>
              current
                ? {
                    ...current,
                    appointment_draft: event.appointment_draft,
                    held_appointment: event.held_appointment,
                    scheduled_appointment: event.scheduled_appointment,
                  }
                : current,
            );
            pushTimeline({
              kind: "appointment",
              title: "Appointment state updated",
              description:
                event.scheduled_appointment?.start_at ||
                event.appointment_draft.requested_time_text ||
                event.appointment_draft.reason_for_visit ||
                "Draft updated",
              timestamp: event.timestamp,
            });
            return;
          }

          case "internal.event": {
            const internalEvent = event as InternalEvent;
            if (internalEvent.event_name === "node_started" && internalEvent.node) {
              setCurrentNode(internalEvent.node);
            }
            if (internalEvent.event_name === "node_finished" && internalEvent.node) {
              setCurrentNode(internalEvent.node);
            }
            pushTimeline({
              kind: "internal",
              title: internalEvent.event_name.replace(/_/g, " "),
              description: internalEvent.node || "Internal backend event",
              timestamp: event.timestamp,
              tone:
                internalEvent.payload.status === "error"
                  ? "danger"
                  : internalEvent.event_name === "node_started"
                    ? "accent"
                    : "default",
              meta: internalEvent.payload.timing
                ? [JSON.stringify(internalEvent.payload.timing)]
                : undefined,
            });
            pushLog({
              level: internalEvent.payload.status === "error" ? "error" : "info",
              message: `${internalEvent.event_name}${internalEvent.node ? `: ${internalEvent.node}` : ""}`,
              timestamp: event.timestamp,
              details: internalEvent.payload,
            });
            return;
          }

          case "log": {
            pushLog({
              level: event.level,
              message: event.message,
              timestamp: event.timestamp,
              details: event.details,
            });
            return;
          }

          case "error": {
            setLastError(event.message);
            setConnectionState("error");
            pushLog({
              level: "error",
              message: event.message,
              timestamp: event.timestamp,
            });
            return;
          }

          case "pong":
            return;
        }
      };

      socket.onerror = () => {
        pushLog({
          level: "error",
          message: "WebSocket transport error.",
          timestamp: new Date().toISOString(),
        });
      };

      socket.onclose = () => {
        clearPingInterval();
        socketRef.current = null;
        if (manualCloseRef.current) {
          setConnectionState("disconnected");
          return;
        }

        setConnectionState("reconnecting");
        const delay = Math.min(5000, 500 * 2 ** reconnectAttemptRef.current);
        reconnectAttemptRef.current += 1;
        reconnectTimerRef.current = window.setTimeout(() => {
          openSocket(targetCallId, true);
        }, delay);
      };
    },
    [
      appendTranscriptMessage,
      clearPingInterval,
      clearReconnectTimer,
      pushLog,
      pushTimeline,
      sendCommand,
      syncPersistedCallData,
    ],
  );

  const connect = useCallback(
    (requestedCallId?: string) => {
      const targetCallId = requestedCallId?.trim() || callIdRef.current || generateCallId();
      manualCloseRef.current = false;
      resetSessionState(targetCallId);
      if (socketRef.current) {
        socketRef.current.close();
      }
      openSocket(targetCallId, false);
    },
    [openSocket, resetSessionState],
  );

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    clearReconnectTimer();
    clearPingInterval();
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setConnectionState("disconnected");
    setStreamingMessage(null);
  }, [clearPingInterval, clearReconnectTimer]);

  const sendUserMessage = useCallback(
    (text: string) => {
      const cleaned = text.trim();
      if (!cleaned) {
        return;
      }
      sendCommand({
        type: "user.message",
        text: cleaned,
      });
    },
    [sendCommand],
  );

  const cancelActiveResponse = useCallback(() => {
    sendCommand({
      type: "assistant.cancel",
    });
  }, [sendCommand]);

  const resetToNewCall = useCallback(() => {
    const nextCallId = generateCallId();
    disconnect();
    resetSessionState(nextCallId);
    return nextCallId;
  }, [disconnect, resetSessionState]);

  useEffect(() => {
    return () => {
      manualCloseRef.current = true;
      clearReconnectTimer();
      clearPingInterval();
      socketRef.current?.close();
    };
  }, [clearPingInterval, clearReconnectTimer]);

  return useMemo(
    () => ({
      callId,
      connectionState,
      session,
      transcript,
      streamingMessage,
      isStreaming: Boolean(streamingMessage),
      currentNode,
      lastError,
      timeline,
      logs,
      connect,
      disconnect,
      sendUserMessage,
      cancelActiveResponse,
      resetToNewCall,
    }),
    [
      callId,
      connectionState,
      session,
      transcript,
      streamingMessage,
      currentNode,
      lastError,
      timeline,
      logs,
      connect,
      disconnect,
      sendUserMessage,
      cancelActiveResponse,
      resetToNewCall,
    ],
  );
}
