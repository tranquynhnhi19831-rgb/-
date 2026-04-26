export default function StartStopPanel({ onStart, onStop }: { onStart: () => void; onStop: () => void }) {
  return (
    <div className="card flex gap-2">
      <button className="btn" onClick={onStart}>启动交易系统</button>
      <button className="btn bg-rose-700 hover:bg-rose-600" onClick={onStop}>停止交易系统</button>
    </div>
  )
}
