import { useEffect, useState } from 'react'
import { api } from '../api/client'
import LogPanel from '../components/LogPanel'

export default function Logs() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api.get('/api/logs').then((r) => setRows(r.data)) }, [])
  return <LogPanel rows={rows} />
}
