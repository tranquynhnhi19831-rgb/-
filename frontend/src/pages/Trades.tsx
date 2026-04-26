import { useEffect, useState } from 'react'
import { api } from '../api/client'
import TradeTable from '../components/TradeTable'

export default function Trades() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api.get('/api/trades').then((r) => setRows(r.data)) }, [])
  return <TradeTable rows={rows} />
}
