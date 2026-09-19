import type {
  ApiResp,
  CandidatesResp,
  EntryOrder,
  HoldingItem,
  KlineResp,
  ScanProgress,
  StatsResp,
  Violation,
  WatchItem,
} from '../types'

async function jget<T>(url: string): Promise<ApiResp<T>> {
  const r = await fetch(url)
  return r.json()
}

async function jpost<T>(url: string, body: unknown): Promise<ApiResp<T>> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

export interface OrderFormPayload {
  code: string
  trade_type: 'A' | 'B' | 'C'
  stop_loss_price: number
  first_target_price: number
  entry_price: number | null
  observed_facts: string
}

export const api = {
  triggerScan: (skipFetch = false) =>
    jpost<{ started: boolean; skip_fetch: boolean }>('/api/scan/run', { skip_fetch: skipFetch }),

  getScanProgress: () =>
    jget<ScanProgress>('/api/scan/progress'),

  getCandidates: (date?: string) =>
    jget<CandidatesResp>(date ? `/api/candidates?date=${date}` : '/api/candidates'),

  getScanDates: () => jget<string[]>('/api/scan/dates'),

  getKline: (code: string, limit = 180) =>
    jget<KlineResp>(`/api/stock/${code}/kline?limit=${limit}`),

  getOrders: (status = 'OPEN') =>
    jget<EntryOrder[]>(`/api/entry-orders?status=${encodeURIComponent(status)}`),

  createOrder: (form: OrderFormPayload) =>
    jpost<{ id: number }>('/api/entry-order', form),

  getHoldings: () => jget<HoldingItem[]>('/api/holdings'),

  confirmExit: (orderId: number) =>
    jpost<{ exited: boolean; hit_rule: string }>(`/api/holdings/${orderId}/exit`, {}),

  getWatchPool: (status = 'ACTIVE') =>
    jget<WatchItem[]>(`/api/watch-pool?status=${encodeURIComponent(status)}`),

  getStats: (month?: string) =>
    jget<StatsResp>(month ? `/api/stats/monthly?month=${month}` : '/api/stats/monthly'),

  getViolations: (limit = 100) => jget<Violation[]>(`/api/violations?limit=${limit}`),
}
