export const connectDashboardWs = (onMessage: (data: any) => void) => {
  const ws = new WebSocket('ws://127.0.0.1:8000/ws/dashboard')
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data))
  return ws
}
