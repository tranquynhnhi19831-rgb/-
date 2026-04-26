import { useEffect, useState } from 'react'
import { api } from '../api/client'
import ConfigForm from '../components/ConfigForm'

export default function Settings() {
  const [cfg, setCfg] = useState<any>({ enabled_symbols: [], allowed_symbols: [] })
  const load = async () => setCfg((await api.get('/api/config')).data)
  useEffect(() => { load() }, [])

  return <ConfigForm cfg={cfg} setCfg={setCfg}
    onSave={async () => { alert(JSON.stringify((await api.post('/api/config', cfg)).data)) }}
    onTestBinance={async () => alert(JSON.stringify((await api.post('/api/config/test-binance', { api_key: cfg.binance_api_key, secret: cfg.binance_secret, testnet: cfg.testnet })).data))}
    onTestDeepseek={async () => alert(JSON.stringify((await api.post('/api/config/test-deepseek', { api_key: cfg.deepseek_api_key })).data))}
  />
}
