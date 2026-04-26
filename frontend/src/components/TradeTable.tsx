export default function TradeTable({ rows }: { rows: any[] }) {
  return (
    <div className="card overflow-auto">
      <h3 className="mb-2">最近交易</h3>
      <table className="w-full text-sm">
        <thead><tr><th>币种</th><th>方向</th><th>开仓</th><th>平仓</th><th>PnL</th><th>dry-run</th><th>理由</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td>{r.symbol}</td><td>{r.side}</td><td>{r.open_time}</td><td>{r.close_time}</td><td>{r.pnl}</td><td>{String(r.dry_run)}</td><td>{r.reason}</td></tr>)}</tbody>
      </table>
    </div>
  )
}
