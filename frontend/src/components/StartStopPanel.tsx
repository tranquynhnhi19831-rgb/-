export default function StartStopPanel({ onStart }: { onStart: () => void; onStop?: () => void }) {
  return (
    <div className="card flex flex-col gap-2">
      <div className="text-sm text-slate-400">
        S7.2 Local Paper 是单次循环验证器，不是后台常驻机器人。每次点击只执行一个 cycle。
      </div>
      <div>
        <button className="btn" onClick={onStart}>执行一次 Paper Cycle</button>
      </div>
    </div>
  )
}
