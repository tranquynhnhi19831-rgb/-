import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { connectDashboardWs } from '../api/websocket'
import StatusCard from '../components/StatusCard'
import PnlChart from '../components/PnlChart'
import TradeTable from '../components/TradeTable'
import PositionTable from '../components/PositionTable'
import SignalTable from '../components/SignalTable'
import LogPanel from '../components/LogPanel'
import StartStopPanel from '../components/StartStopPanel'

export default function Dashboard() {
  const [status, setStatus] = useState<any>({ running: false, mode: 'dry-run' })
  const [account, setAccount] = useState<any>({ balance: 0, daily_pnl: 0, total_pnl: 0, max_drawdown: 0, source: 'simulation' })
  const [trades, setTrades] = useState<any[]>([])
  const [positions, setPositions] = useState<any[]>([])
  const [signals, setSignals] = useState<any[]>([])
  const [logs, setLogs] = useState<any[]>([])
  const [riskEvents, setRiskEvents] = useState<any[]>([])
  const [openOrders, setOpenOrders] = useState<any[]>([])

  const load = async () => {
    const [st, a, t, p, s, l, r, o] = await Promise.all([
      api.get('/api/status'), api.get('/api/account'), api.get('/api/trades'), api.get('/api/positions'), api.get('/api/signals'), api.get('/api/logs'), api.get('/api/risk-events'), api.get('/api/open-orders')
    ])
    setStatus(st.data); setAccount(a.data); setTrades(t.data); setPositions(p.data); setSignals(s.data); setLogs(l.data); setRiskEvents(r.data); setOpenOrders(o.data)
  }

  useEffect(() => {
    load()
    const ws = connectDashboardWs((data) => {
      setStatus({ running: data.running, mode: data.account?.source || 'unknown', last_market_update: data.last_market_update })
      if (data.account) setAccount(data.account)
      if (data.positions) setPositions(data.positions)
      if (data.last_signal) setSignals((prev) => [data.last_signal, ...prev].slice(0, 20))
      if (data.logs) setLogs(data.logs)
      if (data.last_risk_event) setRiskEvents((prev) => [data.last_risk_event, ...prev].slice(0, 20))
      setOpenOrders(data.account?.open_orders || [])
    })
    return () => ws.close()
  }, [])

  return (
    <div className="space-y-4">
      <StartStopPanel onStart={async () => { await api.post('/api/start'); await load() }} onStop={async () => { await api.post('/api/stop'); await load() }} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatusCard title="系统状态" value={status.running ? '运行中' : '已停止'} />
        <StatusCard title="当前模式" value={status.mode} />
        <StatusCard title="数据来源" value={account.source || 'simulation'} />
        <StatusCard title="当前余额" value={account.balance || 0} />
        <StatusCard title="行情更新时间" value={status.last_market_update || '暂无'} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatusCard title="今日盈亏" value={account.daily_pnl || 0} />
        <StatusCard title="总盈亏" value={account.total_pnl || 0} />
        <StatusCard title="最大回撤" value={account.max_drawdown || 0} />
        <StatusCard title="未成交订单" value={openOrders.length} />
      </div>
      <PnlChart data={trades.map((t, i) => ({ x: i, y: t.pnl || 0 }))} />
      <PositionTable rows={positions} />
      <SignalTable rows={signals.slice(0, 1)} />
      <TradeTable rows={trades} />
      <div className="card"><h3>最近一次风控拦截</h3>{riskEvents[0] ? <div>{riskEvents[0].symbol} {riskEvents[0].reason}</div> : <div>暂无</div>}</div>
      <div className="card"><h3>未成交订单</h3>{openOrders.map((o, i) => <div key={i}>{o.symbol} {o.side} {o.amount}</div>)}</div>
      <LogPanel rows={logs} />
    </div>
  )
}
