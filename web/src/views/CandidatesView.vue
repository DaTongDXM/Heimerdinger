<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import type { Candidate, CandidatesResp, Position, ScanProgress } from '../types'
import KlineChart from '../components/KlineChart.vue'

const props = defineProps<{ cand: CandidatesResp | null }>()
const emit = defineEmits<{ (e: 'to-order', row: Candidate): void; (e: 'refresh'): void }>()

const scanning = ref(false)
const progress = ref<ScanProgress | null>(null)
let timer: number | null = null

// --- 日期筛选 ---
const scanDates = ref<string[]>([])
const selectedDate = ref<string>('') // '' = 最新
const historyCand = ref<CandidatesResp | null>(null)

/** 当前展示的数据源：选了历史日期用历史，否则用 App 传入的最新 */
const currentCand = computed<CandidatesResp | null>(() =>
  selectedDate.value ? historyCand.value : props.cand,
)

async function onDateChange(d: string) {
  historyCand.value = null
  if (!d) return
  const r = await api.getCandidates(d)
  if (r.code !== 200) {
    ElMessage.error(r.message)
    selectedDate.value = ''
    return
  }
  historyCand.value = r.data
}

// --- K线抽屉 ---
const drawerVisible = ref(false)
const drawerStock = ref<{ code: string; name: string }>({ code: '', name: '' })

function openKline(row: Candidate) {
  drawerStock.value = { code: row.code, name: row.name }
  drawerVisible.value = true
}

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

/** 扫描中用实时候选流，结束后用最终清单 */
const displayList = computed<Candidate[]>(() =>
  scanning.value ? (progress.value?.candidates ?? []) : (currentCand.value?.candidates ?? []),
)

/** 信号等级 → 中文枚举（S-4 有效组合） */
const SIGNAL_CN: Record<string, string> = {
  STRONG: '强信号',
  STANDARD: '标准信号',
  NONE: '无信号',
}

function signalName(row: Candidate): string {
  const base = SIGNAL_CN[row.signal] ?? row.signal
  const combo = (row.signal_detail as { combo?: string } | null)?.combo
  return combo ? `${base} · ${combo}` : base
}

const groups = computed(() => {
  const list = displayList.value
  const out: { type: string; label: string; rows: Candidate[] }[] = []
  for (const t of ['A', 'B', 'C']) {
    const rows = list.filter((c) => c.type === t && !c.halved)
    if (rows.length) out.push({ type: t, label: GROUP_LABELS[t], rows })
  }
  const v = list.filter((c) => c.halved)
  if (v.length) out.push({ type: 'V', label: GROUP_LABELS.V, rows: v })
  return out
})

const progressPct = computed(() => {
  const p = progress.value
  if (!p || !p.total) return 0
  return Math.min(100, Math.round((p.current / p.total) * 100))
})

// --- 手动触发扫描 ---
async function poll() {
  const r = await api.getScanProgress()
  if (r.code !== 200) return
  progress.value = r.data
  if (r.data.running) {
    timer = window.setTimeout(poll, 2000)
    return
  }
  scanning.value = false
  if (r.data.error) {
    ElMessage.error(`扫描失败：${r.data.error}`)
  } else if (r.data.result) {
    const res = r.data.result
    ElMessage.success(`扫描完成：universe ${res.universe} 只，候选 ${res.candidates} 只` +
      (res.failed_count ? `（${res.failed_count} 只拉取失败，见失败清单）` : ''))
    selectedDate.value = ''
    historyCand.value = null
    api.getScanDates().then((d) => { if (d.code === 200) scanDates.value = d.data })
    emit('refresh')
  }
}

async function startScan(skipFetch: boolean) {
  const r = await api.triggerScan(skipFetch)
  if (r.code !== 200) {
    ElMessage.error(r.message)
    return
  }
  scanning.value = true
  progress.value = { running: true, phase: '启动', current: 0, total: 0,
    started_at: null, finished_at: null, result: null, error: null }
  ElMessage.info(skipFetch ? '正在用本地数据重算扫描…' : '已触发扫描（含日线增量更新，约 10-25 分钟）')
  poll()
}

onMounted(() => {
  api.getScanDates().then((r) => { if (r.code === 200) scanDates.value = r.data })
  // 页面加载时若已有扫描在跑，恢复进度显示
  api.getScanProgress().then((r) => {
    if (r.code === 200 && r.data.running) {
      scanning.value = true
      progress.value = r.data
      poll()
    }
  })
})

onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer)
})
</script>

<template>
  <div class="card">
    <h3 style="display: flex; align-items: center; gap: 12px">
      <span>扫描摘要 · {{ currentCand?.scan_date ?? '—' }}</span>
      <el-select
        v-model="selectedDate"
        size="small"
        clearable
        placeholder="默认最新"
        style="width: 170px"
        :disabled="scanning"
        @change="onDateChange"
      >
        <el-option
          v-for="(d, i) in scanDates"
          :key="d"
          :label="d + (i === 0 ? '（最新）' : '')"
          :value="d"
        />
      </el-select>
      <span style="margin-left: auto; display: flex; gap: 8px">
        <el-button
          size="small"
          type="primary"
          :loading="scanning"
          @click="startScan(false)"
        >
          {{ scanning ? '扫描中…' : '运行扫描' }}
        </el-button>
        <el-button size="small" :disabled="scanning" @click="startScan(true)">
          仅重算（本地数据）
        </el-button>
      </span>
    </h3>

    <div v-if="scanning && progress" style="margin-bottom: 14px">
      <el-progress
        :percentage="progressPct"
        :status="progress.phase === '失败' ? 'exception' : undefined"
      />
      <div class="muted" style="margin-top: 4px">
        {{ progress.phase }} {{ progress.total ? `· ${progress.current}/${progress.total}` : '' }}
        <template v-if="progress.phase === '更新日线'">（增量更新，每只限速 0.3-0.5s）</template>
      </div>
    </div>

    <div class="summary">
      <div class="stat">
        <div class="num">{{ scanning ? (progress?.total ?? 0) : (currentCand?.total ?? 0) }}</div>
        <div class="lbl">{{ scanning ? '扫描总数(进行中)' : '扫描总数' }}</div>
      </div>
      <div class="stat">
        <div class="num pos-up">{{ displayList.length }}</div>
        <div class="lbl">{{ scanning ? '已发现候选' : '候选' }}</div>
      </div>
      <div v-for="(v, k) in currentCand?.counts ?? {}" :key="k" class="stat">
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
      <el-table-column label="代码" width="90">
        <template #default="s">
          <el-link type="primary" :underline="false" @click="openKline(s.row)">
            {{ s.row.code }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column label="位置" width="110">
        <template #default="s">{{ posName(s.row.position) }}</template>
      </el-table-column>
      <el-table-column label="信号" min-width="200">
        <template #default="s">
          <span v-if="s.row.signal === 'NONE'" class="muted">无信号（C类不等信号）</span>
          <span v-else class="pos-up">{{ signalName(s.row) }}</span>
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
    v-if="!scanning && currentCand && !currentCand.candidates.length"
    :description="selectedDate ? `${selectedDate} 无候选` : '今日无候选（先运行扫描）'"
  />
  <el-empty
    v-if="scanning && !displayList.length"
    description="扫描进行中，候选出现后将实时显示在这里…"
  />

  <el-drawer
    v-model="drawerVisible"
    direction="rtl"
    size="640px"
    :title="`${drawerStock.name}（${drawerStock.code}）· 日K`"
    destroy-on-close
  >
    <KlineChart v-if="drawerVisible" :code="drawerStock.code" />
  </el-drawer>
</template>
