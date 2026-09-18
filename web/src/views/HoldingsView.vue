<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { api } from '../api'
import type { ExitAction, HoldingItem } from '../types'

const props = defineProps<{ holdings: HoldingItem[] }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

function actName(a: ExitAction['action']): string {
  return (
    { HOLD: '持有', EXIT: '离场', REDUCE_HALF: '减半', CONVERT_TO_B: '转B类' } as Record<string, string>
  )[a] ?? a
}

function actTag(a: ExitAction['action']): 'info' | 'danger' | 'warning' {
  const map: Record<string, 'info' | 'danger' | 'warning'> = {
    HOLD: 'info',
    EXIT: 'danger',
    REDUCE_HALF: 'warning',
  }
  return map[a] ?? 'info'
}

function fix2(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toFixed(2)
}

async function confirmExit(id: number) {
  const r = await api.confirmExit(id)
  if (r.code === 200) {
    ElMessage.success(r.data.exited ? '已离场并入观察池' : '已减半，剩余仓位按保护线管理')
    emit('refresh')
  } else {
    ElMessage.error(r.message)
  }
}
</script>

<template>
  <div class="card">
    <h3>持仓监控（按入场时锁定的规则判定，输出次日动作）</h3>
    <el-table :data="holdings" size="small" border>
      <el-table-column label="#" width="50">
        <template #default="s">{{ s.row.order.id }}</template>
      </el-table-column>
      <el-table-column label="代码" width="90">
        <template #default="s">{{ s.row.order.code }}</template>
      </el-table-column>
      <el-table-column label="名称" width="130">
        <template #default="s">{{ s.row.order.name }}</template>
      </el-table-column>
      <el-table-column label="类型" width="60">
        <template #default="s">{{ s.row.order.trade_type }}</template>
      </el-table-column>
      <el-table-column label="当前动作" width="100">
        <template #default="s">
          <el-tag :type="actTag(s.row.action.action)" effect="dark">
            {{ actName(s.row.action.action) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="规则" width="90">
        <template #default="s">{{ s.row.action.hit_rule ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="明细" min-width="280">
        <template #default="s">
          <span class="muted">
            收盘 {{ fix2(s.row.action.detail.close) }} · 持有 {{ s.row.action.detail.hold_days }} 日 ·
            {{ s.row.action.detail.next ?? '继续持有' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="s">
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="s.row.action.action !== 'EXIT' && s.row.action.action !== 'REDUCE_HALF'"
            @click="confirmExit(s.row.order.id)"
          >
            确认执行
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!holdings.length" description="无持仓" />
  </div>
</template>
