export default function LogPanel({ rows }: { rows: any[] }) {
  return <div className="card max-h-80 overflow-auto"><h3>系统日志</h3>{rows.map((r) => <div key={r.id}>[{r.category}] {r.message}</div>)}</div>
}
