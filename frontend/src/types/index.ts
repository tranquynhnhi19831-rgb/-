export type AppConfig = {
  binance_api_key: string
  binance_secret: string
  deepseek_api_key: string
  testnet: boolean
  dry_run: boolean
  live_confirmed: boolean
  default_leverage: number
  risk_per_trade: number
  max_daily_loss: number
  enabled_symbols: string[]
  allowed_symbols: string[]
}

export type Trade = Record<string, any>
export type Position = Record<string, any>
export type Signal = Record<string, any>
export type BotLog = Record<string, any>
