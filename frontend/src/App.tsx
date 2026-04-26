import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Trades from './pages/Trades'
import Logs from './pages/Logs'
import Backtest from './pages/Backtest'

const navs = [
  ['/', 'Dashboard'],
  ['/settings', 'Settings'],
  ['/trades', 'Trades'],
  ['/logs', 'Logs'],
  ['/backtest', 'Backtest']
]

export default function App() {
  return (
    <div className="min-h-screen p-4 space-y-4">
      <h1 className="text-2xl font-bold">binance-deepseek-n-trading-bot</h1>
      <div className="flex gap-3">{navs.map(([to, label]) => <NavLink key={to} to={to} className="btn">{label}</NavLink>)}</div>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/trades" element={<Trades />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/backtest" element={<Backtest />} />
      </Routes>
    </div>
  )
}
