import type {
  Summary, ChangesResponse, Service, Method, ParseStatus, StartParseResult,
  Role, AppSettings, SettingsPatch, Proxy, NewProxy, Benchmark,
  HiddenSummary, HiddenService, HiddenMethod,
} from './types'

/** Fired when any API call (except the auth endpoints) gets 401: the session is gone. */
export const UNAUTHORIZED_EVENT = 'bm:unauthorized'

export class HttpError extends Error {
  constructor(readonly status: number, path: string, readonly detail: string | null = null) {
    super(detail ?? `HTTP ${status}: ${path}`)
  }
}

// FastAPI sends {detail: string} or, for validation errors, {detail: [{msg}]}
async function readDetail(res: Response): Promise<string | null> {
  try {
    const body: unknown = await res.json()
    if (!body || typeof body !== 'object' || !('detail' in body)) return null
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const msg = (detail[0] as { msg?: unknown }).msg
      return typeof msg === 'string' ? msg.replace(/^Value error, /, '') : null
    }
    return null
  } catch {
    return null
  }
}

async function request<T>(path: string, init: RequestInit = {}, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    ...(body === undefined ? {} : {
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
    }),
  })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) throw new HttpError(res.status, path, await readDetail(res))
  if (res.status === 204) return undefined as T
  return res.json()
}

const get = <T>(path: string) => request<T>(path)
const send = <T>(method: string, path: string, body?: unknown) => request<T>(path, { method }, body)

export function errorText(e: unknown, fallback: string): string {
  return e instanceof HttpError && e.detail ? e.detail : fallback
}

export const api = {
  me: (): Promise<{ role: Role }> => get('/api/auth/me'),
  login: (password: string): Promise<{ role: Role }> => send('POST', '/api/auth/login', { password }),
  logout: (): Promise<{ ok: boolean }> => send('POST', '/api/auth/logout'),

  summary: (): Promise<Summary> =>
    get('/api/summary'),

  changes: (params: {
    bank?: string
    type?: string
    action?: string
    limit?: number
    offset?: number
  }): Promise<ChangesResponse> => {
    const q = new URLSearchParams()
    if (params.bank) q.set('bank', params.bank)
    if (params.type) q.set('type', params.type)
    if (params.action) q.set('action', params.action)
    if (params.limit != null) q.set('limit', String(params.limit))
    if (params.offset != null) q.set('offset', String(params.offset))
    return get(`/api/changes?${q}`)
  },

  services: (bank: string): Promise<{ services: Service[] }> =>
    get(`/api/services?bank=${encodeURIComponent(bank)}`),

  methods: (serviceId: number): Promise<{ methods: Method[] }> =>
    get(`/api/methods?service_id=${serviceId}`),

  parseStatus: (): Promise<ParseStatus> =>
    get('/api/parse/status'),

  startParse: async (): Promise<StartParseResult> => {
    try {
      const data = await send<{ status: 'started' | 'already_running' }>('POST', '/api/parse')
      return data.status
    } catch (e) {
      if (e instanceof HttpError && e.status === 403) return 'forbidden'
      throw e
    }
  },

  settings: (): Promise<AppSettings> => get('/api/settings'),
  saveSettings: (patch: SettingsPatch): Promise<AppSettings> => send('PUT', '/api/settings', patch),

  proxies: (): Promise<{ proxies: Proxy[] }> => get('/api/proxies'),
  addProxy: (proxy: NewProxy): Promise<Proxy> => send('POST', '/api/proxies', proxy),
  deleteProxy: (id: number): Promise<void> => send('DELETE', `/api/proxies/${id}`),
  checkProxy: (id: number): Promise<Proxy> => send('POST', `/api/proxies/${id}/check`),
  checkAllProxies: (): Promise<{ proxies: Proxy[] }> => send('POST', '/api/proxies/check'),

  benchmark: (): Promise<Benchmark> => get('/api/benchmark'),
  /** present: null puts the cell back to automatic matching. */
  setBenchmarkOverride: (capability: string, bank: string, present: boolean | null): Promise<Benchmark> =>
    send('PUT', '/api/benchmark/overrides', { capability, bank, present }),

  // Admin-only: services/methods kept in the DB but not shown on the public dashboard.
  hiddenSummary: (): Promise<HiddenSummary> =>
    get('/api/hidden/summary'),

  hiddenServices: (bank: string): Promise<{ services: HiddenService[] }> =>
    get(`/api/hidden/services?bank=${encodeURIComponent(bank)}`),

  hiddenMethods: (serviceId: number): Promise<{ methods: HiddenMethod[] }> =>
    get(`/api/hidden/methods?service_id=${serviceId}`),
}
