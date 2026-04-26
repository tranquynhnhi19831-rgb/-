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
  const [account, setAccount] = useState<any>({ balance: 0, daily_pnl: 0, total_pnl: 0, max_drawdown: 0 })
  const [trades, setTrades] = useState<any[]>([])
  const [positions, setPositions] = useState<any[]>([])
  const [signals, setSignals] = useState<any[]>([])
  const [logs, setLogs] = useState<any[]>([])
  const [riskEvents, setRiskEvents] = useState<any[]>([])

  const load = async () => {
    const [a, t, p, s, l, r] = await Promise.all([
      api.get('/api/account'), api.get('/api/trades'), api.get('/api/positions'), api.get('/api/signals'), api.get('/api/logs'), api.get('/api/risk-events')
    ])
    setAccount(a.data); setTrades(t.data); setPositions(p.data); setSignals(s.data); setLogs(l.data); setRiskEvents(r.data)
  }

  useEffect(() => {
    load()
    const ws = connectDashboardWs((data) => { if (data.type === 'account') setAccount(data.payload) })
    return () => ws.close()
  }, [])

  return (
    <div className="space-y-4">
      <StartStopPanel onStart={async () => { await api.post('/api/start'); await load() }} onStop={async () => { await api.post('/api/stop'); await load() }} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatusCard title="当前余额" value={account.balance} />
        <StatusCard title="今日盈亏" value={account.daily_pnl} />
        <StatusCard title="总盈亏" value={account.total_pnl} />
        <StatusCard title="最大回撤" value={account.max_drawdown} />
        <StatusCard title="模式" value="dry-run/testnet 默认" />
      </div>
      <PnlChart data={trades.map((t, i) => ({ x: i, y: t.pnl || 0 }))} />
      <PositionTable rows={positions} />
      <SignalTable rows={signals} />
      <TradeTable rows={trades} />
      <div className="card"><h3>风控拦截记录</h3>{riskEvents.map((x) => <div key={x.id}>{x.symbol} {x.reason}</div>)}</div>
      <LogPanel rows={logs} />
    </div>
  )
}
