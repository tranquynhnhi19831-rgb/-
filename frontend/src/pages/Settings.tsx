import { useEffect, useState } from 'react'
import { api } from '../api/client'
import ConfigForm from '../components/ConfigForm'

export default function Settings() {
  const [cfg, setCfg] = useState<any>({ enabled_symbols: [], allowed_symbols: [] })
  const load = async () => {
    const data = (await api.get('/api/config')).data
    setCfg({ ...data, binance_api_key: '', binance_secret: '', deepseek_api_key: '' })
  }
  useEffect(() => { load() }, [])

  return <ConfigForm cfg={cfg} setCfg={setCfg}
    onSave={async () => { alert(JSON.stringify((await api.post('/api/config', cfg)).data)); await load() }}
    onTestBinance={async () => alert(JSON.stringify((await api.post('/api/config/test-binance', { api_key: cfg.binance_api_key, secret: cfg.binance_secret, testnet: cfg.testnet })).data))}
    onTestDeepseek={async () => {
      try {
        const res = await api.post('/api/config/test-deepseek', { api_key: cfg.deepseek_api_key, base_url: cfg.deepseek_base_url, model: cfg.deepseek_model })
        alert(JSON.stringify(res.data))
      } catch (e: any) {
        alert(JSON.stringify(e?.response?.data || String(e)))
      }
    }}
  />
}
