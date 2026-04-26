export default function SignalTable({ rows }: { rows: any[] }) {
  return <div className="card"><h3>最近策略信号</h3>{rows.map((r) => <div key={r.id}>{r.symbol} {r.signal_type} score:{r.score}</div>)}</div>
}
