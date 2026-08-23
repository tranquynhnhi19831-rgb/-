from dataclasses import dataclass

from config import HARD_MAX_LEVERAGE, HARD_MAX_RISK_PER_TRADE


@dataclass
class RiskContext:
    equity: float
    daily_pnl: float
    trades_today: int
    open_positions: int
    consecutive_losses: int


class RiskManager:
    def risk_budget_usdt(self, cfg: dict, equity: float) -> float:
        risk_per_trade = float(cfg.get("risk_per_trade", 0.0))
        if risk_per_trade <= 0 or risk_per_trade > HARD_MAX_RISK_PER_TRADE:
            raise ValueError("invalid risk_per_trade")
        return max(0.0, float(equity)) * risk_per_trade

    def check(
        self,
        cfg: dict,
        ctx: RiskContext,
        symbol: str,
        rr: float,
        leverage: int,
        margin_ratio: float,
    ) -> tuple[bool, str]:
        configured_max_leverage = min(int(cfg.get("max_leverage", 1)), HARD_MAX_LEVERAGE)
        if leverage < 1 or leverage > configured_max_leverage:
            return False, f"杠杆超过当前限制(>{configured_max_leverage})"
        if cfg.get("margin_mode") != "isolated":
            return False, "只允许逐仓 isolated"

        max_daily_loss = float(cfg.get("max_daily_loss", 0.0))
        if max_daily_loss <= 0:
            return False, "每日最大亏损参数无效"
        if ctx.daily_pnl <= -(ctx.equity * max_daily_loss):
            return False, "达到每日最大亏损阈值"

        if ctx.trades_today >= int(cfg.get("max_trades_per_day", 0)):
            return False, "达到单日交易上限"
        if ctx.open_positions >= int(cfg.get("max_open_positions", 0)):
            return False, "超过最大持仓数"
        if ctx.consecutive_losses >= int(cfg.get("max_consecutive_losses", 0)):
            return False, "连续亏损达到上限"
        if rr < 1.5:
            return False, "盈亏比不足1.5"
        if margin_ratio <= 0 or margin_ratio > float(cfg.get("max_margin_per_trade", 0.0)):
            return False, "单笔保证金超过上限"

        risk_per_trade = float(cfg.get("risk_per_trade", 0.0))
        if risk_per_trade <= 0 or risk_per_trade > HARD_MAX_RISK_PER_TRADE:
            return False, "单笔风险比例必须在0到1%之间"
        if symbol not in cfg.get("enabled_symbols", []):
            return False, "币种未启用"
        return True, "ok"
