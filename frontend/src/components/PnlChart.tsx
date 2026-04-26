import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts'

export default function PnlChart({ data }: { data: any[] }) {
  return (
    <div className="card h-64">
      <div className="mb-2">收益曲线</div>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={data}>
          <XAxis dataKey="x" hide />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="y" stroke="#60a5fa" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
