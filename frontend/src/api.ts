import type { Summary, ChangesResponse, Dynamic, Service, Method, Field } from './types'

const BASE = ''

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`)
  return res.json()
}

export const api = {
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

  dynamics: (): Promise<{ dynamics: Dynamic[] }> =>
    get('/api/dynamics'),

  services: (bank: string): Promise<{ services: Service[] }> =>
    get(`/api/services?bank=${bank}`),

  methods: (serviceId: number): Promise<{ methods: Method[] }> =>
    get(`/api/methods?service_id=${serviceId}`),

  fields: (methodId: number): Promise<{ fields: Field[] }> =>
    get(`/api/fields?method_id=${methodId}`),
}
