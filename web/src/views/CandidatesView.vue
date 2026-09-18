<script setup lang="ts">
import { computed } from 'vue'
import type { Candidate, CandidatesResp, Position } from '../types'

const props = defineProps<{ cand: CandidatesResp | null }>()
const emit = defineEmits<{ (e: 'to-order', row: Candidate): void }>()

const POS_NAME: Record<Position, string> = {
  BOTTOM_REVERSAL: '底部反转',
  PULLBACK_UPTREND: '多头回踩',
  DOWNTREND_CONTINUATION: '下跌中继',
  V_SHAPE: 'V型',
  OTHER: '未分类',
}

function posName(p: string): string {
  return POS_NAME[p as Position] ?? p
}

function fix2(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toFixed(2)
}

const GROUP_LABELS: Record<string, string> = {
  A: 'A 类 · 短线动量（1-3日，单层）',
  B: 'B 类 · 波段跟随（5-20日，回踩加仓）',
  C: 'C 类 · 左侧分批（20-60日，不等信号）',
  V: 'V 型标记（仓位强制减半）',
}

const groups = computed(() => {
  const list = props.cand?.candidates ?? []
  const out: { type: string; label: string; rows: Candidate[] }[] = []
  for (const t of ['A', 'B', 'C']) {
    const rows = list.filter((c) => c.type === t && !c.halved)
    if (rows.length) out.push({ type: t, label: GROUP_LABELS[t], rows })
  }
  const v = list.filter((c) => c.halved)
  if (v.length) out.push({ type: 'V', label: GROUP_LABELS.V, rows: v })
  return out
})
</script>

<template>
  <div class="card">
    <h3>扫描摘要 · {{ cand?.scan_date ?? '—' }}</h3>
    <div class="summary">
      <div class="stat">
        <div class="num">{{ cand?.total ?? 0 }}</div>
        <div class="lbl">扫描总数</div>
      </div>
      <div class="stat">
        <div class="num pos-up">{{ (cand?.candidates ?? []).length }}</div>
        <div class="lbl">候选</div>
      </div>
      <div v-for="(v, k) in cand?.counts ?? {}" :key="k" class="stat">
        <div class="num" :class="k === 'DOWNTREND_CONTINUATION' ? 'pos-down' : ''">{{ v }}</div>
        <div class="lbl">{{ posName(k) }}</div>
      </div>
    </div>
    <div class="muted" style="margin-top: 10px">
      下跌中继已在阶段②硬过滤，不进入信号计算。
    </div>
  </div>

  <div v-for="g in groups" :key="g.type" class="card">
    <h3>{{ g.label }}（{{ g.rows.length }}）</h3>
    <el-table :data="g.rows" size="small" border>
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column label="位置" width="110">
        <template #default="s">{{ posName(s.row.position) }}</template>
      </el-table-column>
      <el-table-column label="信号" width="110">
        <template #default="s">
          <span v-if="s.row.signal === 'NONE'" class="muted">无（C类不等信号）</span>
          <span v-else class="pos-up">{{ s.row.signal }}</span>
        </template>
      </el-table-column>
      <el-table-column label="建议关注位" min-width="240">
        <template #default="s">
          <span v-if="s.row.ref_platform_top">平台上沿 {{ fix2(s.row.ref_platform_top) }} / </span>
          <span v-if="s.row.ref_ma20">MA20 {{ fix2(s.row.ref_ma20) }} / </span>
          <span>前日收盘 {{ fix2(s.row.ref_prev_close) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="加仓计划" min-width="220">
        <template #default="s">
          <span v-if="s.row.add_plan" class="muted">
            失效价 {{ fix2(s.row.add_plan.invalidate_price) }}；加仓
            {{ (s.row.add_plan.add_prices ?? []).map((p: number) => fix2(p)).join(' / ') }}
          </span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="s">
          <el-button size="small" type="primary" plain @click="emit('to-order', s.row)">
            填入场单
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <el-empty
    v-if="cand && !cand.candidates.length"
    description="今日无候选（先运行 python -m timoo.cli scan）"
  />
</template>
