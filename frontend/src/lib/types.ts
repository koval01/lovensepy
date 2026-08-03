/** Types mirroring the service payloads (`GET /state`, `/system/network`, …). */

export type TransportName = "lan" | "ble" | "socket";

export interface Transports {
  lan: boolean;
  ble: boolean;
  socket: boolean;
}

export interface ToyView {
  id: string;
  name: string;
  nick_name: string;
  toy_type: string | null;
  firmware: string | null;
  battery: number | null;
  online: boolean;
  features: string[];
  transport: "ble" | "app";
  ble: {
    address: string | null;
    connected: boolean;
    model_letter: string | null;
  } | null;
}

export type TaskKind = "function" | "function_loop" | "preset" | "pattern";

export interface TaskRow {
  task_id: string;
  kind: TaskKind;
  toy_id: string | null;
  feature?: string;
  level?: number;
  duration_sec?: number | null;
  duration_requested_sec?: number | null;
  remaining_sec: number | null;
  started_at: string;
  preset?: string;
  interval?: number;
  pattern_length?: number;
  pattern_preview?: number[];
  pattern_actions?: string[] | null;
  template?: string;
  actions?: Record<string, number>;
  loop_on_time?: number | null;
  loop_off_time?: number | null;
  extension_count?: number;
}

export interface Capabilities {
  actions: string[];
  controllable_actions: string[];
  presets: string[];
  pattern_templates: Record<string, number[]>;
  function_ranges: Record<string, [number, number]>;
  pattern_limits: {
    max_steps: number;
    min_level: number;
    max_level: number;
    interval_ms: [number, number];
  };
}

export interface BleAdvertisement {
  address: string;
  name: string | null;
  rssi: number | null;
}

export interface BleRegistryRow {
  toy_id: string;
  address: string;
  connected: boolean;
  name: string;
  nickName: string;
  toy_type: string | null;
  firmware: string | null;
  model_letter: string | null;
  features: string[];
  battery: number | null;
}

export interface SupervisorToyStatus {
  paused: boolean;
  attempts: number;
  reconnects: number;
  last_error: string | null;
  retry_in_sec: number;
  connected_for_sec: number | null;
  recent: string[];
}

export interface SupervisorStatus {
  enabled: boolean;
  running: boolean;
  interval_sec: number;
  battery_refresh_sec: number;
  rounds: number;
  last_round_age_sec: number | null;
  toys: Record<string, SupervisorToyStatus>;
}

export interface BleState {
  registry: BleRegistryRow[];
  advertisements: BleAdvertisement[];
  monitor: { enabled: boolean; interval_sec: number };
  scan: { timeout_sec: number; name_prefix: string | null };
  supervisor: SupervisorStatus;
}

export interface SocketState {
  status: {
    socket_io_connected?: boolean;
    app_online?: boolean | null;
    app_status?: number | null;
    toy_ids?: string[];
    local_commands?: boolean;
  };
  qr: {
    qrcodeUrl?: string | null;
    qrcode?: string | null;
    ackId?: string | null;
  };
}

export interface ServiceConfigView {
  mode: string;
  app_name: string;
  session_max_sec: number;
  lan: { ip: string | null; port: number; enabled: boolean };
  ble: {
    enabled: boolean;
    scan_timeout_sec: number;
    scan_name_prefix: string | null;
    advertisement_monitor: boolean;
    advertisement_monitor_interval_sec: number;
    preset_uart_keyword: string;
    preset_emulate_pattern: boolean;
    auto_reconnect: boolean;
    auto_reconnect_interval_sec: number;
    battery_refresh_sec: number;
  };
  socket: {
    enabled: boolean;
    platform: string | null;
    uname: string | null;
    has_developer_token: boolean;
    has_uid: boolean;
    use_local_commands: boolean;
    auto_request_qr: boolean;
  };
  webui_enabled: boolean;
  events_interval_sec: number;
  tunnel: {
    enabled: boolean;
    listen_port: number | null;
    listen_host: string;
  };
  external_gate: boolean;
}

export interface PendingAccessApproval {
  id: string;
  ip: string | null;
  country: string | null;
  device: string;
  browser: string;
  user_agent: string | null;
  created_ago_sec: number;
  expires_in_sec: number;
}

export interface GateStatus {
  enabled: boolean;
  code_pending: boolean;
  code_expires_in_sec: number | null;
  active_sessions: number;
  pending_approval_count?: number;
  /** Host-only: live 6-digit challenge digits. Never sent to tunnel visitors. */
  code?: string | null;
  display?: string | null;
  /** Host-only: Cloudflare visitors waiting for Allow / Deny. */
  pending_approvals?: PendingAccessApproval[];
}

export interface AccessCodeInfo {
  status: string;
  code: string | null;
  display: string | null;
  expires_in_sec: number | null;
}

export type ViewerRole = "host" | "remote";

export interface PresenceSelf {
  client_id: string;
  role: ViewerRole;
  device: string;
  browser: string;
}

export interface RemoteClient {
  client_id: string;
  online: boolean;
  connected_for_sec: number;
  idle_for_sec: number;
  ip: string | null;
  country: string | null;
  device: string;
  browser: string;
  user_agent: string | null;
  tab: string | null;
  activity: string | null;
  activity_age_sec: number | null;
  rtt_ms: number | null;
  rtt_age_sec: number | null;
}

export interface PresenceState {
  self: PresenceSelf | null;
  remotes: RemoteClient[];
  hosts_online: number;
  remotes_online: number;
}

export type AccessCapability = "control" | "admin" | "setup";

export interface AccessInfo {
  role: ViewerRole;
  capabilities: AccessCapability[];
}

export interface TunnelStatus {
  available: boolean;
  binary: string | null;
  desired: boolean;
  running: boolean;
  url: string | null;
  local_url: string | null;
  pid: number | null;
  last_error: string | null;
  restarts: number;
  uptime_sec: number | null;
  recent: string[];
}

export interface ServiceState {
  rev: number;
  version: string;
  server_time: string;
  uptime_sec: number;
  mode: string;
  transports: Transports;
  configured: boolean;
  config: ServiceConfigView;
  capabilities: Capabilities;
  toys: ToyView[];
  tasks: TaskRow[];
  toys_error: string | null;
  ble: BleState | null;
  socket: SocketState | null;
  tunnel: TunnelStatus;
  gate: GateStatus;
  presence: PresenceState;
  /** Present on current servers; older builds may omit it. */
  access?: AccessInfo;
}

export interface NetworkInfo {
  scheme: string;
  port: number;
  hostname: string;
  local_url: string;
  lan_addresses: string[];
  lan_urls: string[];
  primary_url: string;
  tunnel_url: string | null;
  tunnel: TunnelStatus | null;
  request_host: string | null;
  secure_context: boolean;
}

export interface ScanDevice {
  address: string;
  name: string | null;
  rssi: number | null;
  suggested_toy_id: string;
  toy_type: string | null;
  registered: boolean;
}

export interface AutoConnectResult {
  scanned: number;
  connected: string[];
  results: Array<{
    address?: string | null;
    toy_id?: string;
    name?: string | null;
    ok: boolean;
    error?: string;
  }>;
  toys: BleRegistryRow[];
}

/** Live link state of the browser → service channel. */
export type LinkStatus = "connecting" | "live" | "polling" | "offline";
