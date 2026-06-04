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

export interface Dynamic {
  week: string
  count: number
  bank: string
  label: string
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
  request_example: Record<string, unknown>
  response_example: Record<string, unknown>
}

export interface Field {
  id: number
  name: string
  type: string
  required: boolean
}

export type BankKey = 'tbank' | 'alfabank' | 'sber' | 'tochka'
