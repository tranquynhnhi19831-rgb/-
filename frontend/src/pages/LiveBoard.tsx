import { useEffect, useMemo, useState } from 'react'

import { publicApi } from '../api/publicClient'

type Position = {
  id: number
  symbol: string
  side: string
  entry_price: number
  mark_price: number
  quantity: number
  notional_usdt: number
  leverage: number
  unrealized_pnl: number
}

type Trade = {
  id: number
  symbol: string
  side: string
  open_time: string | null
  close_time: string | null
  entry_price: number
  exit_price: number
  quantity: number
  leverage: number
  fee: number
  pnl: number
  dry_run: boolean
  strategy_reason: string
}

type Snapshot = {
  read_only: boolean
  updated_at: string
  account: {
    equity: number
    balance: number
    daily_pnl: number
    total_pnl: number
    max_drawdown: number
    initial_capital_usdt: number
    total_return_pct: number
  }
  positions: Position[]
  recent_trades: Trade[]
  statistics: {
    closed_trades: number
    wins: number
    losses: number
    win_rate_pct: number
  }
}

const money = (value: number | null | undefined, digits = 2) => Number(value || 0).toFixed(digits)

export default function LiveBoard() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const response = await publicApi.get<Snapshot>('/api/public/snapshot')
      setSnapshot(response.data)
      setError('')
    } catch (err) {
      setError('展示盘暂时无法取得最新数据')
    }
  }

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 3000)
    return () => window.clearInterval(timer)
  }, [])

  const positionPnl = useMemo(
    () => (snapshot?.positions || []).reduce((sum, row) => sum + Number(row.unrealized_pnl || 0), 0),
    [snapshot]
  )

  if (!snapshot) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <div className="max-w-6xl mx-auto card">{error || '正在加载实时展示盘…'}</div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-8">
      <div className="max-w-6xl mx-auto space-y-4">
        <header className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
          <div>
            <div className="text-xs tracking-[0.25em] text-slate-400">JIANGHE QUANT LIVE</div>
            <h1 className="text-3xl font-bold mt-1">量化交易实时展示盘</h1>
            <p className="text-sm text-slate-400 mt-2">只读展示 · 无启动、停止、配置或下单能力</p>
          </div>
          <div className="text-sm text-right">
            <div className="font-semibold">● READ ONLY</div>
            <div className="text-slate-400">更新：{new Date(snapshot.updated_at).toLocaleString()}</div>
          </div>
        </header>

        {error && <div className="card">{error}，当前显示上一次成功快照。</div>}

        <section className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <Metric title="初始资金" value={`${money(snapshot.account.initial_capital_usdt)} U`} />
          <Metric title="当前权益" value={`${money(snapshot.account.equity)} U`} />
          <Metric title="累计收益" value={`${money(snapshot.account.total_return_pct)}%`} />
          <Metric title="未实现盈亏" value={`${money(positionPnl)} U`} />
          <Metric title="已完成交易" value={`${snapshot.statistics.closed_trades}`} />
          <Metric title="胜率" value={`${money(snapshot.statistics.win_rate_pct)}%`} />
        </section>

        <section className="card overflow-x-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">当前持仓</h2>
            <span className="text-sm text-slate-400">{snapshot.positions.length} 个仓位</span>
          </div>
          {snapshot.positions.length === 0 ? (
            <div className="py-6 text-slate-400">当前没有持仓</div>
          ) : (
            <table className="w-full text-sm min-w-[760px]">
              <thead className="text-slate-400 text-left">
                <tr>
                  <th className="py-2">标的</th>
                  <th>方向</th>
                  <th>入场价</th>
                  <th>标记价</th>
                  <th>数量</th>
                  <th>仓位价值</th>
                  <th>杠杆</th>
                  <th>未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.positions.map((row) => (
                  <tr key={row.id} className="border-t border-slate-800">
                    <td className="py-3 font-medium">{row.symbol}</td>
                    <td>{String(row.side).toUpperCase()}</td>
                    <td>{money(row.entry_price, 4)}</td>
                    <td>{money(row.mark_price, 4)}</td>
                    <td>{money(row.quantity, 6)}</td>
                    <td>{money(row.notional_usdt)} U</td>
                    <td>{row.leverage}x</td>
                    <td>{money(row.unrealized_pnl)} U</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card overflow-x-auto">
          <h2 className="text-lg font-semibold mb-3">最近交易</h2>
          {snapshot.recent_trades.length === 0 ? (
            <div className="py-6 text-slate-400">暂无交易记录</div>
          ) : (
            <table className="w-full text-sm min-w-[900px]">
              <thead className="text-slate-400 text-left">
                <tr>
                  <th className="py-2">标的</th>
                  <th>方向</th>
                  <th>入场</th>
                  <th>出场</th>
                  <th>数量</th>
                  <th>PnL</th>
                  <th>手续费</th>
                  <th>模式</th>
                  <th>策略理由</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.recent_trades.map((row) => (
                  <tr key={row.id} className="border-t border-slate-800 align-top">
                    <td className="py-3 font-medium">{row.symbol}</td>
                    <td>{String(row.side).toUpperCase()}</td>
                    <td>{money(row.entry_price, 4)}</td>
                    <td>{money(row.exit_price, 4)}</td>
                    <td>{money(row.quantity, 6)}</td>
                    <td>{money(row.pnl)} U</td>
                    <td>{money(row.fee, 4)} U</td>
                    <td>{row.dry_run ? 'DRY-RUN' : 'LIVE'}</td>
                    <td className="max-w-xs text-slate-300">{row.strategy_reason || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <footer className="text-xs text-slate-500 pb-6">
          该页面仅展示服务器已记录的账户/持仓/交易数据，不提供任何交易操作入口。
        </footer>
      </div>
    </main>
  )
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="card">
      <div className="text-xs text-slate-400">{title}</div>
      <div className="text-xl font-semibold mt-2">{value}</div>
    </div>
  )
}
