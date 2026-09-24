export interface BankStat {
  name: string
  label: string
  services: number
  methods: number
}

export interface Summary {
  banks: BankStat[]
  total_services: number
  total_methods: number
  changes_today: number
  changes_week: number
  changes_total: number
}

export interface Change {
  id: number
  bank: string
  bank_label: string
  type: 'service' | 'method' | 'field'
  action: 'added' | 'removed' | 'modified'
  entity: string
  path: string
  old_value: string
  new_value: string
  url: string
  detected_at: string
}

export interface ChangesResponse {
  changes: Change[]
  total: number
  limit: number
  offset: number
}

export interface Service {
  id: number
  name: string
  url: string
}

export interface Method {
  id: number
  name: string
  http_method: string
  path: string
  url: string
  request_example: unknown
  response_example: unknown
}

export interface BankParseStatus {
  status: 'pending' | 'running' | 'done' | 'error'
  started_at: string | null
  finished_at: string | null
  services: number
  methods: number
  changes: number
  error: string | null
}

export interface ParseStatus {
  running: boolean
  started_at: string | null
  finished_at: string | null
  banks: Record<string, BankParseStatus>
}

export type StartParseResult = 'started' | 'already_running' | 'forbidden'

export type Role = 'admin' | 'team'

export interface AppSettings {
  scheduler_time: string          // HH:MM, Moscow time
  proxy_enabled: boolean
  next_run: string | null         // "dd.mm, HH:MM"
}

export type SettingsPatch = Partial<Pick<AppSettings, 'scheduler_time' | 'proxy_enabled'>>

export interface Proxy {
  id: number
  url: string                     // password already masked by the server
  label: string
  expires_at: string | null       // dd.mm.YYYY
  days_left: number | null        // negative once expired
  last_checked_at: string | null
  last_ok: boolean | null
  last_ip: string | null
  last_country: string | null
  last_latency_ms: number | null
  last_error: string | null
}

export interface NewProxy {
  url: string
  label: string
  days?: number
  expires_on?: string             // YYYY-MM-DD
}

export interface BenchmarkEvidence {
  service: string
  matched: number                 // methods that count for the row
  total: number                   // all methods of the service
  by_name: boolean                // the service name itself matched
}

export interface BenchmarkCell {
  present: boolean                // what the table shows: override ?? auto
  auto: boolean
  override: boolean | null
  evidence: BenchmarkEvidence[]
}

export interface BenchmarkRow {
  key: string
  title: string
  cells: Record<string, BenchmarkCell>
}

export interface BenchmarkBank {
  key: string
  label: string
  snapshot_at: string | null      // dd.mm.YYYY HH:MM, Moscow time
}

export interface Benchmark {
  banks: BenchmarkBank[]
  groups: { title: string; rows: BenchmarkRow[] }[]
  unmatched: Record<string, string[]>
}

/**
 * Why a method/service is hidden from the public dashboard but kept in the DB.
 * The backend enum is fixed to these four values, but the type stays a plain
 * string at the API boundary so an unrecognised value can't crash the UI.
 */
export type HiddenReason = 'private' | 'superseded' | 'not_in_menu' | 'ghost'

export interface HiddenBankSummary {
  name: string
  label: string
  hidden_services: number
  hidden_methods: number
  by_reason: Record<string, number>
}

export interface HiddenSummary {
  banks: HiddenBankSummary[]
}

export interface HiddenService {
  id: number
  name: string
  url: string
}

export interface HiddenMethod {
  id: number
  name: string
  http_method: string
  path: string
  url: string
  hidden_reason: string
  request_example: unknown
  response_example: unknown
}
