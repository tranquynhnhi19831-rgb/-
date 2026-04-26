import { useState } from 'react'
import { api } from '../api/client'

export default function Backtest() {
  const [symbol, setSymbol] = useState('BTC/USDT')
  const [start, setStart] = useState('2025-01-01')
  const [end, setEnd] = useState('2025-12-31')
  const [res, setRes] = useState<any>(null)

  return (
    <div className="card space-y-2">
      <h3>回测</h3>
      <input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
      <input className="input" value={start} onChange={(e) => setStart(e.target.value)} />
      <input className="input" value={end} onChange={(e) => setEnd(e.target.value)} />
      <button className="btn" onClick={async () => setRes((await api.post('/api/backtest/run', { symbol, start, end })).data)}>运行回测</button>
      {res && <pre>{JSON.stringify(res, null, 2)}</pre>}
    </div>
  )
}
