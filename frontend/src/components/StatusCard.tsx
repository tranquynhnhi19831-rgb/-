export default function StatusCard({ title, value }: { title: string; value: string | number }) {
  return (
    <div className="card">
      <div className="text-xs text-slate-400">{title}</div>
      <div className="text-xl font-semibold mt-1">{value}</div>
    </div>
  )
}
