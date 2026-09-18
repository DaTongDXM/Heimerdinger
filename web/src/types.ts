export interface ApiResp<T> {
  code: number
  message: string
  data: T
}

export interface AddPlan {
  invalidate_price: number
  space_pct: number
  step_pct: number
  add_prices: number[]
  max_layers: number
}

export type Position =
  | 'BOTTOM_REVERSAL'
  | 'PULLBACK_UPTREND'
  | 'DOWNTREND_CONTINUATION'
  | 'V_SHAPE'
  | 'OTHER'

export interface Candidate {
  code: string
  name: string
  type: 'A' | 'B' | 'C'
  position: Position
  halved: boolean
  signal: string
  signal_detail: Record<string, unknown>
  ref_platform_top: number | null
  ref_platform_bottom: number | null
  ref_ma20: number | null
  ref_prev_close: number | null
  add_plan: AddPlan | null
}

export interface CandidatesResp {
  scan_date: string
  param_version: string
  counts: Record<string, number>
  total: number
  candidates: Candidate[]
}

export interface EntryOrder {
  id: number
  code: string
  name: string
  scan_date: string | null
  trade_type: 'A' | 'B' | 'C'
  structure_position: string
  observed_facts: string
  stop_loss_price: number
  first_target_price: number
  remainder_protection: string
  time_stop_days: number
  self_check_pass: number
  entry_price: number | null
  layers: number
  status: string
  created_at: string
}

export interface ExitAction {
  action: 'HOLD' | 'EXIT' | 'REDUCE_HALF' | 'CONVERT_TO_B'
  hit_rule: string | null
  exit_type: string | null
  detail: {
    close?: number
    hold_days?: number
    next?: string
    [k: string]: unknown
  }
}

export interface HoldingItem {
  order: EntryOrder
  action: ExitAction
}

export interface WatchItem {
  id: number
  code: string
  source_exit_type: string
  reentry_trigger: { branch?: string; rule?: string; recover_price?: number } | string
  status: string
  entered_date: string
  cleared_date: string | null
  days_remaining: number
}

export interface TypeStat {
  trades: number
  wins: number
  pnl_sum: number
  win_rate: number | null
  avg_pnl: number | null
}

export interface StatsResp {
  month: string
  by_type: Record<string, TypeStat>
  total_exits: number
  par: number | null
  sample_gate: { current: number; required: number; unlocked: boolean }
}

export interface Violation {
  id: number
  date: string
  rule_id: string
  code: string | null
  detail: string | null
}

export interface ScanProgress {
  running: boolean
  phase: string
  current: number
  total: number
  started_at: string | null
  finished_at: string | null
  result: {
    scan_date: string
    universe: number
    failed_count: number
    counts: Record<string, number>
    candidates: number
    output: string
  } | null
  error: string | null
  /** 扫描过程中实时产出的候选（仅 running 时有意义） */
  candidates?: Candidate[]
}
