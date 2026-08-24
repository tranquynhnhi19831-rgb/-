from dataclasses import dataclass

from config import HARD_MAX_LEVERAGE, HARD_MAX_RISK_PER_TRADE


@dataclass
class RiskContext:
    equity: float
    daily_pnl: float
    trades_today: int
    open_positions: int
    consecutive_losses: int
    day_start_equity: float | None = None


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    code: str
    message: str


class RiskManager:
    def risk_budget_usdt(self, cfg: dict, equity: float) -> float:
        risk_per_trade = float(cfg.get("risk_per_trade", 0.0))
        if risk_per_trade <= 0 or risk_per_trade > HARD_MAX_RISK_PER_TRADE:
            raise ValueError("invalid risk_per_trade")
        return max(0.0, float(equity)) * risk_per_trade

    def evaluate(
        self,
        cfg: dict,
        ctx: RiskContext,
        symbol: str,
        rr: float,
        leverage: int,
        margin_ratio: float,
    ) -> RiskDecision:
        configured_max_leverage = min(int(cfg.get("max_leverage", 1)), HARD_MAX_LEVERAGE)
        if leverage < 1 or leverage > configured_max_leverage:
            return RiskDecision(False, "MAX_LEVERAGE_EXCEEDED", f"杠杆超过当前限制(>{configured_max_leverage})")
        if cfg.get("margin_mode") != "isolated":
            return RiskDecision(False, "MARGIN_MODE_NOT_ISOLATED", "只允许逐仓 isolated")

        max_daily_loss = float(cfg.get("max_daily_loss", 0.0))
        if max_daily_loss <= 0:
            return RiskDecision(False, "INVALID_MAX_DAILY_LOSS", "每日最大亏损参数无效")

        day_start_equity = float(ctx.day_start_equity or 0.0)
        if day_start_equity <= 0:
            # For the Paper ledger, current equity - today's realized PnL is the
            # best deterministic reconstruction of start-of-day equity.
            day_start_equity = max(0.0, float(ctx.equity) - float(ctx.daily_pnl))
        if day_start_equity > 0 and ctx.daily_pnl <= -(day_start_equity * max_daily_loss):
            return RiskDecision(False, "MAX_DAILY_LOSS_REACHED", "达到每日最大亏损阈值")

        if ctx.trades_today >= int(cfg.get("max_trades_per_day", 0)):
            return RiskDecision(False, "MAX_TRADES_PER_DAY_REACHED", "达到单日交易上限")
        if ctx.open_positions >= int(cfg.get("max_open_positions", 0)):
            return RiskDecision(False, "MAX_OPEN_POSITIONS_REACHED", "超过最大持仓数")

        # ``consecutive_losses`` is reconstructed from the latest ledger rows and
        # may include the previous UTC day. Never let an old streak permanently
        # deadlock the system: only losses that could have occurred among today's
        # already-opened trades are eligible for the current-day cooldown. This
        # preserves the intended semantics: three consecutive losses stop new
        # entries for the rest of that UTC day, then the next UTC day starts clean.
        current_day_loss_streak = min(
            max(0, int(ctx.consecutive_losses)),
            max(0, int(ctx.trades_today)),
        )
        max_consecutive_losses = int(cfg.get("max_consecutive_losses", 0))
        if max_consecutive_losses <= 0:
            return RiskDecision(False, "INVALID_MAX_CONSECUTIVE_LOSSES", "连续亏损上限参数无效")
        if current_day_loss_streak >= max_consecutive_losses:
            return RiskDecision(False, "MAX_CONSECUTIVE_LOSSES_REACHED", "当日连续亏损达到上限")

        if rr < 1.5:
            return RiskDecision(False, "MIN_RR_NOT_MET", "盈亏比不足1.5")
        if margin_ratio <= 0 or margin_ratio > float(cfg.get("max_margin_per_trade", 0.0)):
            return RiskDecision(False, "MAX_MARGIN_PER_TRADE_EXCEEDED", "单笔保证金超过上限")

        risk_per_trade = float(cfg.get("risk_per_trade", 0.0))
        if risk_per_trade <= 0 or risk_per_trade > HARD_MAX_RISK_PER_TRADE:
            return RiskDecision(False, "INVALID_RISK_PER_TRADE", "单笔风险比例必须在0到1%之间")
        if symbol not in cfg.get("enabled_symbols", []):
            return RiskDecision(False, "SYMBOL_NOT_ENABLED", "币种未启用")
        return RiskDecision(True, "OK", "ok")

    def check(
        self,
        cfg: dict,
        ctx: RiskContext,
        symbol: str,
        rr: float,
        leverage: int,
        margin_ratio: float,
    ) -> tuple[bool, str]:
        """Backward-compatible tuple API used by existing callers/tests."""

        decision = self.evaluate(cfg, ctx, symbol, rr, leverage, margin_ratio)
        return decision.allowed, decision.message
