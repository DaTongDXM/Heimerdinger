<script setup lang="ts">
import type { WatchItem } from '../types'

defineProps<{ watch: WatchItem[] }>()

function trigText(t: WatchItem['reentry_trigger']): string {
  if (!t) return '—'
  if (typeof t === 'string') return t || '—'
  return t.rule ?? '—'
}
</script>

<template>
  <div class="card">
    <h3>观察池（出场后强制入池，20 个交易日无触发自动清除）</h3>
    <el-table :data="watch" size="small" border>
      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="source_exit_type" label="出场类型" width="120" />
      <el-table-column label="再入场触发" min-width="280">
        <template #default="s">{{ trigText(s.row.reentry_trigger) }}</template>
      </el-table-column>
      <el-table-column prop="entered_date" label="入池日期" width="110" />
      <el-table-column label="剩余观察" width="100">
        <template #default="s">
          <el-tag :type="s.row.days_remaining <= 5 ? 'danger' : 'info'">
            {{ s.row.days_remaining }} 日
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
    </el-table>
    <el-empty v-if="!watch.length" description="观察池为空" />
  </div>
</template>
