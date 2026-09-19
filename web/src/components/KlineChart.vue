<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { dispose, init, type Chart, type KLineData } from 'klinecharts'
import { api } from '../api'
import type { KlineBar } from '../types'

const props = defineProps<{ code: string }>()

const el = ref<HTMLDivElement>()
const loading = ref(true)
const empty = ref(false)
const emptyTip = ref('本地无该股K线数据')
let chart: Chart | null = null

/** 中国惯例：涨红跌绿 */
const CN_CANDLE_STYLES = {
  candle: {
    bar: {
      upColor: '#F0284A',
      downColor: '#2DC08E',
      noChangeColor: '#909399',
      upBorderColor: '#F0284A',
      downBorderColor: '#2DC08E',
      noChangeBorderColor: '#909399',
      upWickColor: '#F0284A',
      downWickColor: '#2DC08E',
      noChangeWickColor: '#909399',
    },
  },
}

function toBars(rows: KlineBar[]): KLineData[] {
  return rows.map((r) => ({
    timestamp: new Date(`${r.date}T00:00:00`).getTime(),
    open: r.open,
    high: r.high,
    low: r.low,
    close: r.close,
    volume: r.vol,
  }))
}

onMounted(async () => {
  if (!el.value) return
  chart = init(el.value, { locale: 'zh-CN', styles: CN_CANDLE_STYLES })
  if (!chart) return
  chart.setBarSpace(8)
  // MA 是 overlay 指标 → 叠加在蜡烛图；VOL 非 overlay → 自动新建副图
  chart.createIndicator({ name: 'MA', calcParams: [5, 20, 60] }, false)
  chart.createIndicator({ name: 'VOL', calcParams: [5] }, false)
  chart.setDataLoader({
    getBars: ({ callback }) => {
      api.getKline(props.code, 180).then((r) => {
        loading.value = false
        if (r.code !== 200 || !r.data?.rows?.length) {
          // 404 = 后端旧进程无此端点；200 但空 = 该股确实没下载到K线
          empty.value = true
          emptyTip.value = r.code !== 200
            ? 'K线接口不存在：请重启服务（后端是旧进程）'
            : '本地无该股K线数据（可能下载失败，见失败清单）'
          callback([])
          return
        }
        callback(toBars(r.data.rows))
        chart?.scrollToRealTime(0)
      })
    },
  })
  // v10：必须设置 symbol + period 才会触发 dataLoader 拉数
  chart.setSymbol({ ticker: props.code, pricePrecision: 2, volumePrecision: 0 })
  chart.setPeriod({ type: 'day', span: 1 })
})

onBeforeUnmount(() => {
  if (chart && el.value) dispose(el.value)
  chart = null
})
</script>

<template>
  <div class="kline-wrap">
    <div v-if="loading" class="kline-tip">加载K线中…</div>
    <div v-else-if="empty" class="kline-tip">{{ emptyTip }}</div>
    <div ref="el" class="kline-canvas" :style="{ visibility: loading || empty ? 'hidden' : 'visible' }" />
  </div>
</template>

<style scoped>
.kline-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 480px;
}
.kline-canvas {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
.kline-tip {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 13px;
}
</style>
