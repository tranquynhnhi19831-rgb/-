from dataclasses import dataclass


@dataclass
class RiskContext:
    equity: float
    daily_pnl: float
    trades_today: int
    open_positions: int
    consecutive_losses: int


class RiskManager:
    def check(self, cfg: dict, ctx: RiskContext, symbol: str, rr: float, leverage: int, margin_ratio: float) -> tuple[bool, str]:
        if leverage > min(cfg["max_leverage"], 5):
            return False, "杠杆超过限制(>5)"
        if cfg["margin_mode"] != "isolated":
            return False, "只允许逐仓 isolated"
        if ctx.daily_pnl <= -(ctx.equity * cfg["max_daily_loss"]):
            return False, "达到每日最大亏损阈值"
        if ctx.trades_today >= cfg["max_trades_per_day"]:
            return False, "达到单日交易上限"
        if ctx.open_positions >= cfg["max_open_positions"]:
            return False, "超过最大持仓数"
        if ctx.consecutive_losses >= cfg["max_consecutive_losses"]:
            return False, "连续亏损达到上限"
        if rr < 1.5:
            return False, "盈亏比不足1.5"
        if margin_ratio > cfg["max_margin_per_trade"]:
            return False, "单笔保证金超过上限"
        if cfg["risk_per_trade"] > 0.01:
            return False, "单笔风险比例必须<=1%"
        if symbol not in cfg["enabled_symbols"]:
            return False, "币种未启用"
        return True, "ok"
