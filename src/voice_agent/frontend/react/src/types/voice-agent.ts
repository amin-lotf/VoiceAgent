export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

export interface LiveMessage {
  id: string;
  role: "assistant" | "user" | "system";
  content: string;
  created_at?: string | null;
  response_id?: number | null;
}

export interface LiveMetrics {
  ttft_s?: number | null;
  total_latency_s?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
}

export interface LiveAppointmentDraft {
  name?: string | null;
  phone?: string | null;
  reason_for_visit?: string | null;
  requested_time_text?: string | null;
  requested_time_iso?: string | null;
  last_offered_slot_start_at?: string | null;
  offered_time_confirmed?: boolean | null;
  status?: string | null;
  notes: string[];
}

export interface LiveAppointmentView {
  id: number;
  name?: string | null;
  phone?: string | null;
  reason_for_visit?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  notes: string[];
  status?: string | null;
  patient_type?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface LiveCallState {
  call_id: string;
  status: string;
  phase?: string | null;
  assistant_phase?: string | null;
  next_action?: string | null;
  assistant_intent?: string | null;
  user_intent?: string | null;
  current_node?: string | null;
  end_call: boolean;
  messages: LiveMessage[];
  appointment_draft: LiveAppointmentDraft;
  held_appointment?: LiveAppointmentView | null;
  scheduled_appointment?: LiveAppointmentView | null;
  metrics: LiveMetrics;
  node_data: Record<string, Record<string, unknown>>;
}

export interface LiveCapabilities {
  cancel_active_response: boolean;
  dashboard_available: boolean;
  logs_available: boolean;
}

export interface SessionReadyEvent {
  type: "session.ready";
  timestamp: string;
  call_id: string;
  state: LiveCallState;
  capabilities: LiveCapabilities;
}

export interface StateSnapshotEvent {
  type: "state.snapshot";
  timestamp: string;
  state: LiveCallState;
}

export interface UserMessageEvent {
  type: "user.message";
  timestamp: string;
  message: LiveMessage;
}

export interface AssistantStartedEvent {
  type: "assistant.response.started";
  timestamp: string;
  response_id: number;
  trigger?: string | null;
}

export interface AssistantDeltaEvent {
  type: "assistant.response.delta";
  timestamp: string;
  response_id: number;
  delta: string;
}

export interface AssistantCompletedEvent {
  type: "assistant.response.completed";
  timestamp: string;
  response_id: number;
  message: LiveMessage;
  metrics: LiveMetrics;
  end_call: boolean;
  state: LiveCallState;
}

export interface AssistantCancelledEvent {
  type: "assistant.response.cancelled";
  timestamp: string;
  response_id?: number | null;
  reason: string;
}

export interface PhaseChangedEvent {
  type: "phase.changed";
  timestamp: string;
  phase?: string | null;
  assistant_phase?: string | null;
  next_action?: string | null;
  current_node?: string | null;
}

export interface AppointmentUpdatedEvent {
  type: "appointment.updated";
  timestamp: string;
  appointment_draft: LiveAppointmentDraft;
  held_appointment?: LiveAppointmentView | null;
  scheduled_appointment?: LiveAppointmentView | null;
}

export interface InternalEvent {
  type: "internal.event";
  timestamp: string;
  event_name: string;
  node?: string | null;
  payload: Record<string, unknown>;
}

export interface LogEvent {
  type: "log";
  timestamp: string;
  level: "debug" | "info" | "warning" | "error";
  message: string;
  details?: Record<string, unknown> | null;
}

export interface ErrorEvent {
  type: "error";
  timestamp: string;
  message: string;
}

export interface PongEvent {
  type: "pong";
  timestamp: string;
  client_timestamp?: number | null;
}

export type LiveServerEvent =
  | SessionReadyEvent
  | StateSnapshotEvent
  | UserMessageEvent
  | AssistantStartedEvent
  | AssistantDeltaEvent
  | AssistantCompletedEvent
  | AssistantCancelledEvent
  | PhaseChangedEvent
  | AppointmentUpdatedEvent
  | InternalEvent
  | LogEvent
  | ErrorEvent
  | PongEvent;

export interface UserMessageCommand {
  type: "user.message";
  text: string;
}

export interface AssistantCancelCommand {
  type: "assistant.cancel";
}

export interface SessionSnapshotCommand {
  type: "session.snapshot";
}

export interface PingCommand {
  type: "ping";
  timestamp?: number;
}

export type LiveClientCommand =
  | UserMessageCommand
  | AssistantCancelCommand
  | SessionSnapshotCommand
  | PingCommand;

export interface TimelineEntry {
  id: string;
  kind: "assistant" | "user" | "phase" | "appointment" | "internal" | "system";
  title: string;
  description?: string;
  timestamp: string;
  tone?: "default" | "accent" | "warning" | "danger";
  meta?: string[];
}

export interface LogEntry {
  id: string;
  level: "debug" | "info" | "warning" | "error";
  message: string;
  timestamp: string;
  details?: Record<string, unknown> | null;
}

export interface CallLog {
  level: "debug" | "info" | "warning" | "error";
  message: string;
  timestamp: string;
  details?: Record<string, unknown> | null;
}

export interface CallSummary {
  call_id: string;
  started_at: string;
  ended_at?: string | null;
  duration_seconds?: number | null;
  final_status?: string | null;
  total_tokens: number;
  avg_total_delay_s?: number | null;
  avg_first_token_delay_s?: number | null;
}

export interface CallTurn {
  role: string;
  content: string;
  created_at?: string | null;
  total_tokens?: number | null;
  total_delay_s?: number | null;
  first_token_delay_s?: number | null;
}

export interface CallDetail extends CallSummary {
  turns: CallTurn[];
  logs: CallLog[];
  scheduled_appointment?: LiveAppointmentView | null;
}
