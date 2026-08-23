import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Trades from './pages/Trades'
import Logs from './pages/Logs'
import Backtest from './pages/Backtest'
import LiveBoard from './pages/LiveBoard'

const navs = [
  ['/', 'Dashboard'],
  ['/settings', 'Settings'],
  ['/trades', 'Trades'],
  ['/logs', 'Logs'],
  ['/backtest', 'Backtest']
]

export default function App() {
  const location = useLocation()

  // /live is deliberately rendered outside the admin shell. The public
  // deployment exposes this page with backend.public_main only, so visitors
  // never receive Settings/Start/Stop routes from the public API service.
  if (location.pathname === '/live') {
    return <LiveBoard />
  }

  return (
    <div className="min-h-screen p-4 space-y-4">
      <h1 className="text-2xl font-bold">jianghe-quant-system</h1>
      <div className="flex gap-3">{navs.map(([to, label]) => <NavLink key={to} to={to} className="btn">{label}</NavLink>)}</div>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/trades" element={<Trades />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/live" element={<LiveBoard />} />
      </Routes>
    </div>
  )
}
