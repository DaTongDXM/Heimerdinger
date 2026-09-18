<script setup lang="ts">
import { reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import type { Candidate, EntryOrder } from '../types'

const props = defineProps<{ orders: EntryOrder[]; prefill: Candidate | null }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

const form = reactive({
  code: '',
  trade_type: 'A' as 'A' | 'B' | 'C',
  stop_loss_price: null as number | null,
  first_target_price: null as number | null,
  entry_price: null as number | null,
  observed_facts: '',
})

// 候选行"填入场单"带入
watch(
  () => props.prefill,
  (row) => {
    if (!row) return
    form.code = row.code
    form.trade_type = row.type
    if (row.add_plan) form.stop_loss_price = Number(row.add_plan.invalidate_price)
    if (row.ref_platform_top) form.first_target_price = Number(row.ref_platform_top)
    if (row.ref_prev_close) form.entry_price = Number(row.ref_prev_close)
    ElMessage.info(`已带入 ${row.code}（${row.type} 类），请核对止损/目标价后提交`)
  },
)

async function submitOrder() {
  if (!form.code || form.stop_loss_price == null || form.first_target_price == null) {
    ElMessage.warning('请填写代码、止损价、目标价')
    return
  }
  const r = await api.createOrder({
    code: form.code,
    trade_type: form.trade_type,
    stop_loss_price: Number(form.stop_loss_price),
    first_target_price: Number(form.first_target_price),
    entry_price: form.entry_price,
    observed_facts: form.observed_facts,
  })
  if (r.code === 200) {
    ElMessage.success(`入场单 #${r.data.id} 已保存（append-only）`)
    form.observed_facts = ''
    emit('refresh')
  } else {
    ElMessage.error(r.message)
  }
}
</script>

<template>
  <div class="card">
    <h3>入场单（8 项强制校验，缺一项不开仓）</h3>
    <el-form :model="form" label-width="130px" style="max-width: 640px">
      <el-form-item label="股票代码" required>
        <el-input v-model="form.code" placeholder="如 600000" style="width: 200px" />
      </el-form-item>
      <el-form-item label="0. 交易类型" required>
        <el-radio-group v-model="form.trade_type">
          <el-radio-button value="A">A 短线动量</el-radio-button>
          <el-radio-button value="B">B 波段跟随</el-radio-button>
          <el-radio-button value="C">C 左侧分批</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="3. 固定止损价" required>
        <el-input-number
          v-model="form.stop_loss_price"
          :precision="2"
          :controls="false"
          style="width: 200px"
        />
        <span class="muted" style="margin-left: 8px">A=前日收盘价；C=平台下沿×0.98</span>
      </el-form-item>
      <el-form-item label="4. 第一目标价" required>
        <el-input-number
          v-model="form.first_target_price"
          :precision="2"
          :controls="false"
          style="width: 200px"
        />
        <span class="muted" style="margin-left: 8px">结构位（前高/平台上沿），到位减半</span>
      </el-form-item>
      <el-form-item label="入场价（参考）">
        <el-input-number
          v-model="form.entry_price"
          :precision="2"
          :controls="false"
          style="width: 200px"
        />
      </el-form-item>
      <el-form-item label="2. 观察到的事实" required>
        <el-input
          v-model="form.observed_facts"
          type="textarea"
          :rows="2"
          placeholder="只写观察，禁写预测（含'即将/预计/大概率'会被拒绝）"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="submitOrder">提交入场单</el-button>
      </el-form-item>
    </el-form>
    <el-alert
      type="info"
      :closable="false"
      title="第 1/5/6 项（结构位置、剩余仓位保护线、时间止损）由系统按类型自动锁定；第 7 项自检（盈利后 30 分钟冷却）由系统强制执行。"
    />
  </div>

  <div class="card">
    <h3>已保存入场单（append-only，不可修改）</h3>
    <el-table :data="orders" size="small" border>
      <el-table-column prop="id" label="#" width="50" />
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="130" />
      <el-table-column prop="trade_type" label="类型" width="60" />
      <el-table-column prop="stop_loss_price" label="止损价" width="90" />
      <el-table-column prop="first_target_price" label="目标价" width="90" />
      <el-table-column prop="time_stop_days" label="时间止损(日)" width="100" />
      <el-table-column prop="status" label="状态" width="80" />
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
    </el-table>
  </div>
</template>
