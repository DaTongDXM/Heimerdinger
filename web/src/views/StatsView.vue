<script setup lang="ts">
import { computed } from 'vue'
import type { StatsResp, TypeStat, Violation } from '../types'

const props = defineProps<{ stats: StatsResp | null; violations: Violation[] }>()

const gate = computed(() => props.stats?.sample_gate ?? { current: 0, required: 20, unlocked: false })

const byTypeRows = computed(() =>
  Object.entries(props.stats?.by_type ?? {}).map(([t, d]: [string, TypeStat]) => ({ t, ...d })),
)

const gatePct = computed(() =>
  Math.min(100, Math.round((gate.value.current / gate.value.required) * 100)),
)
</script>

<template>
  <div class="card">
    <h3>本月复盘 · {{ stats?.month ?? '—' }}</h3>
    <div class="summary">
      <div class="stat">
        <div class="num">{{ stats?.total_exits ?? 0 }}</div>
        <div class="lbl">出场笔数</div>
      </div>
      <div class="stat">
        <div class="num pos-up">
          {{ stats?.par == null ? '—' : (stats.par * 100).toFixed(0) + '%' }}
        </div>
        <div class="lbl">计划执行率 PAR（北极星）</div>
      </div>
      <div class="stat" style="min-width: 260px">
        <div style="font-size: 13px; margin-bottom: 6px">
          参数调优样本门禁：{{ gate.current }} / {{ gate.required }}
        </div>
        <el-progress :percentage="gatePct" :status="gate.unlocked ? 'success' : 'warning'" />
        <div class="muted" style="margin-top: 4px">
          {{ gate.unlocked ? '已解锁（仍需先回测）' : '样本不足，禁止调参' }}
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>分类型统计</h3>
    <el-table :data="byTypeRows" size="small" border>
      <el-table-column prop="t" label="类型" width="80" />
      <el-table-column prop="trades" label="笔数" width="80" />
      <el-table-column label="胜率" width="100">
        <template #default="s">
          {{ s.row.win_rate == null ? '—' : (s.row.win_rate * 100).toFixed(0) + '%' }}
        </template>
      </el-table-column>
      <el-table-column label="平均盈亏" min-width="120">
        <template #default="s">
          <span :class="s.row.avg_pnl > 0 ? 'pos-up' : 'pos-down'">
            {{ s.row.avg_pnl == null ? '—' : (s.row.avg_pnl * 100).toFixed(2) + '%' }}
          </span>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <div class="card">
    <h3>违规记录（N1-N8）</h3>
    <el-table :data="violations" size="small" border>
      <el-table-column prop="date" label="日期" width="110" />
      <el-table-column prop="rule_id" label="规则" width="80" />
      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="detail" label="详情" min-width="240" />
    </el-table>
    <el-empty v-if="!violations.length" description="无违规记录" />
  </div>
</template>
