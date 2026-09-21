<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from './api'
import type {
  Candidate,
  CandidatesResp,
  EntryOrder,
  HoldingItem,
  StatsResp,
  Violation,
  WatchItem,
} from './types'
import CandidatesView from './views/CandidatesView.vue'
import OrderView from './views/OrderView.vue'
import HoldingsView from './views/HoldingsView.vue'
import WatchView from './views/WatchView.vue'
import StatsView from './views/StatsView.vue'

const tab = ref('candidates')
const cand = ref<CandidatesResp | null>(null)
const orders = ref<EntryOrder[]>([])
const holdings = ref<HoldingItem[]>([])
const watch = ref<WatchItem[]>([])
const stats = ref<StatsResp | null>(null)
const violations = ref<Violation[]>([])
const prefill = ref<Candidate | null>(null)

const statusLine = computed(() => {
  const n = cand.value?.candidates?.length ?? 0
  return `候选 ${n} · 持仓 ${holdings.value.length} · 观察 ${watch.value.length} · 违规 ${violations.value.length}`
})

async function refresh() {
  const [c, o, h, w, s, v] = await Promise.all([
    api.getCandidates(),
    api.getOrders(),
    api.getHoldings(),
    api.getWatchPool(),
    api.getStats(),
    api.getViolations(),
  ])
  if (c.code === 200) cand.value = c.data
  orders.value = o.code === 200 ? o.data : []
  holdings.value = h.code === 200 ? h.data : []
  watch.value = w.code === 200 ? w.data : []
  if (s.code === 200) stats.value = s.data
  violations.value = v.code === 200 ? v.data : []
}

function onToOrder(row: Candidate) {
  prefill.value = row
  tab.value = 'order'
}

async function checkBackend() {
  try {
    const r = await api.getVersion()
    if (r.code !== 200) throw new Error('bad response')
  } catch {
    ElMessage.error({
      message: '后端是旧进程：K线抽屉、日期筛选等新功能不可用。请关闭 start.bat 命令行窗口后重新双击启动。',
      duration: 0,
      showClose: true,
    })
  }
}

onMounted(() => {
  checkBackend()
  refresh()
})
</script>

<template>
  <div class="topbar">
    <span class="brand">Heimerdinger</span>
    <el-menu
      :default-active="tab"
      mode="horizontal"
      background-color="#1f2d3d"
      text-color="#cfd8e3"
      active-text-color="#ffffff"
      style="border-bottom: none"
      @select="(t: string) => (tab = t)"
    >
      <el-menu-item index="candidates">候选池</el-menu-item>
      <el-menu-item index="order">入场单</el-menu-item>
      <el-menu-item index="holdings">持仓</el-menu-item>
      <el-menu-item index="watch">观察池</el-menu-item>
      <el-menu-item index="stats">复盘</el-menu-item>
    </el-menu>
    <span class="status">{{ statusLine }}</span>
  </div>

  <div class="container">
    <CandidatesView v-if="tab === 'candidates'" :cand="cand" @to-order="onToOrder" @refresh="refresh" />
    <OrderView v-if="tab === 'order'" :orders="orders" :prefill="prefill" @refresh="refresh" />
    <HoldingsView v-if="tab === 'holdings'" :holdings="holdings" @refresh="refresh" />
    <WatchView v-if="tab === 'watch'" :watch="watch" />
    <StatsView v-if="tab === 'stats'" :stats="stats" :violations="violations" />
  </div>
</template>
