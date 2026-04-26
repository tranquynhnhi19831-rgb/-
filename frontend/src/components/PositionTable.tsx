export default function PositionTable({ rows }: { rows: any[] }) {
  return <div className="card"><h3>当前持仓</h3>{rows.map((r) => <div key={r.id}>{r.symbol} {r.side} qty:{r.quantity}</div>)}</div>
}
