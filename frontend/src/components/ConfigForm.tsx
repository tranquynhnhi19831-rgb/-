export default function ConfigForm({ cfg, setCfg, onSave, onTestBinance, onTestDeepseek }: any) {
  const symbols = cfg.allowed_symbols || []
  const toggle = (s: string) => {
    const next = new Set(cfg.enabled_symbols || [])
    next.has(s) ? next.delete(s) : next.add(s)
    setCfg({ ...cfg, enabled_symbols: [...next] })
  }
  return (
    <div className="card space-y-3">
      <div className="rounded border border-emerald-900 bg-emerald-950/30 p-3 text-sm text-emerald-200">
        Binance Demo Key / Secret 仅从后端进程环境变量读取。此页面不接收、不保存、也不回显 Binance 凭证。
        本地 Demo 请使用 <code>scripts/start_demo_backend.ps1</code> 安全启动。
      </div>
      <div className="rounded border border-slate-800 p-3 text-sm text-slate-400">
        Mainnet 下单当前不支持；Demo 实际下单路由默认关闭。Settings 仅管理 Paper 风控与策略范围。
      </div>
      <input className="input" placeholder="DeepSeek Key" value={cfg.deepseek_api_key || ''} onChange={(e) => setCfg({ ...cfg, deepseek_api_key: e.target.value })} />
      <label><input type="checkbox" checked={Boolean(cfg.testnet)} onChange={(e) => setCfg({ ...cfg, testnet: e.target.checked })} /> testnet / demo research mode</label>
      <label><input type="checkbox" checked={Boolean(cfg.dry_run)} onChange={(e) => setCfg({ ...cfg, dry_run: e.target.checked })} /> dry-run</label>
      <label>杠杆（最大 5）<input className="input" type="number" max={5} value={cfg.default_leverage ?? 1} onChange={(e) => setCfg({ ...cfg, default_leverage: Number(e.target.value) })} /></label>
      <label>单笔风险比例<input className="input" type="number" step="0.001" value={cfg.risk_per_trade ?? 0.005} onChange={(e) => setCfg({ ...cfg, risk_per_trade: Number(e.target.value) })} /></label>
      <label>每日最大亏损比例<input className="input" type="number" step="0.001" value={cfg.max_daily_loss ?? 0.02} onChange={(e) => setCfg({ ...cfg, max_daily_loss: Number(e.target.value) })} /></label>
      <div className="grid grid-cols-2 gap-2">{symbols.map((s: string) => <label key={s}><input type="checkbox" checked={cfg.enabled_symbols?.includes(s)} onChange={() => toggle(s)} /> {s}</label>)}</div>
      <div className="flex flex-wrap gap-2">
        <button className="btn" onClick={onSave}>保存 Paper 配置</button>
        <button className="btn" onClick={onTestBinance}>只读测试 Binance Demo</button>
        <button className="btn" onClick={onTestDeepseek}>测试 DeepSeek</button>
      </div>
    </div>
  )
}
