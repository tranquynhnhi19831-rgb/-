import { AppConfig } from '../types'

export default function ConfigForm({ cfg, setCfg, onSave, onTestBinance, onTestDeepseek }: any) {
  const symbols = cfg.allowed_symbols || []
  const toggle = (s: string) => {
    const set = new Set(cfg.enabled_symbols)
    if (set.has(s)) set.delete(s)
    else set.add(s)
    setCfg({ ...cfg, enabled_symbols: [...set] })
  }

  return (
    <div className="card space-y-3">
      <div className="text-amber-400">⚠ API Key 禁止开启提现权限，只开启读取和交易权限。</div>
      <input className="input" placeholder="Binance API Key" value={cfg.binance_api_key || ''} onChange={(e) => setCfg({ ...cfg, binance_api_key: e.target.value })} />
      <input className="input" placeholder="Binance Secret" value={cfg.binance_secret || ''} onChange={(e) => setCfg({ ...cfg, binance_secret: e.target.value })} />
      <input className="input" placeholder="DeepSeek API Key" value={cfg.deepseek_api_key || ''} onChange={(e) => setCfg({ ...cfg, deepseek_api_key: e.target.value })} />
      <label><input type="checkbox" checked={cfg.testnet} onChange={(e) => setCfg({ ...cfg, testnet: e.target.checked })} /> testnet</label>
      <label><input type="checkbox" checked={cfg.dry_run} onChange={(e) => setCfg({ ...cfg, dry_run: e.target.checked })} /> dry-run</label>
      <label><input type="checkbox" checked={cfg.live_confirmed} onChange={(e) => setCfg({ ...cfg, live_confirmed: e.target.checked })} /> live二次确认</label>
      <label>杠杆(<=5)<input className="input" type="number" max={5} value={cfg.default_leverage} onChange={(e) => setCfg({ ...cfg, default_leverage: Number(e.target.value) })} /></label>
      <label>单笔风险比例<input className="input" type="number" step="0.001" value={cfg.risk_per_trade} onChange={(e) => setCfg({ ...cfg, risk_per_trade: Number(e.target.value) })} /></label>
      <label>每日最大亏损比例<input className="input" type="number" step="0.001" value={cfg.max_daily_loss} onChange={(e) => setCfg({ ...cfg, max_daily_loss: Number(e.target.value) })} /></label>
      <div className="grid grid-cols-2 gap-2">{symbols.map((s: string) => <label key={s}><input type="checkbox" checked={cfg.enabled_symbols?.includes(s)} onChange={() => toggle(s)} /> {s}</label>)}</div>
      <div className="flex gap-2">
        <button className="btn" onClick={onSave}>保存配置</button>
        <button className="btn" onClick={onTestBinance}>测试Binance连接</button>
        <button className="btn" onClick={onTestDeepseek}>测试DeepSeek连接</button>
      </div>
    </div>
  )
}
