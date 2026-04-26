from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskContext:
    equity: float
    daily_pnl: float
    trades_today: int
    open_positions: int
    consecutive_losses: int
    has_open_orders: bool
    has_same_side_position: bool
    has_opposite_position: bool
    seconds_since_last_trade: int
    volatility_ratio: float


class RiskManager:
    def check(
        self,
        cfg: dict,
        ctx: RiskContext,
        symbol: str,
        signal: dict,
        market_limits: dict,
        fee_rate: float = 0.0004,
        slippage_rate: float = 0.0005,
    ) -> tuple[bool, str, dict]:
        if cfg["default_leverage"] > min(cfg["max_leverage"], 5):
            return False, "杠杆超过限制(>5)", {}
        if cfg["margin_mode"] != "isolated":
            return False, "只允许逐仓 isolated", {}
        if not cfg["dry_run"] and not cfg["testnet"] and not cfg["live_confirmed"]:
            return False, "live 模式必须二次确认", {}
        if ctx.daily_pnl <= -(ctx.equity * cfg["max_daily_loss"]):
            return False, "达到每日最大亏损阈值", {}
        if ctx.trades_today >= cfg["max_trades_per_day"]:
            return False, "达到单日交易上限", {}
        if ctx.open_positions >= cfg["max_open_positions"]:
            return False, "超过最大持仓数", {}
        if ctx.consecutive_losses >= cfg["max_consecutive_losses"]:
            return False, "连续亏损达到上限", {}
        if ctx.has_open_orders:
            return False, "存在未成交订单", {}
        if ctx.has_same_side_position:
            return False, "同向仓位禁止重复开仓", {}
        if ctx.has_opposite_position:
            return False, "存在反向仓位，需先平仓", {}
        if ctx.seconds_since_last_trade < cfg["cooldown_seconds"]:
            return False, "冷却时间未结束", {}
        if ctx.volatility_ratio > 0.08:
            return False, "异常波动过滤触发", {}

        entry = float(signal["entry"])
        stop = float(signal["stop_loss"])
        take = float(signal["take_profit"])
        side = signal["side"]
        if side == "long":
            risk_per_unit = entry - stop
            reward_per_unit = take - entry
        else:
            risk_per_unit = stop - entry
            reward_per_unit = entry - take

        if risk_per_unit <= 0:
            return False, "止损距离非法", {}
        rr = reward_per_unit / risk_per_unit
        if rr < 1.5:
            return False, "盈亏比不足1.5", {}

        risk_budget = ctx.equity * cfg["risk_per_trade"]
        qty = max(risk_budget / risk_per_unit, 0)

        step = float(((market_limits.get("amount") or {}).get("min") or 0.001))
        qty = round(qty / step) * step if step > 0 else qty
        qty = max(qty, step)

        price_precision = int(market_limits.get("price_precision", 2))
        amount_precision = int(market_limits.get("amount_precision", 3))
        entry = round(entry, price_precision)
        stop = round(stop, price_precision)
        take = round(take, price_precision)
        qty = round(qty, amount_precision)

        notional = entry * qty / max(cfg["default_leverage"], 1)
        if notional > (ctx.equity * cfg["max_margin_per_trade"]):
            return False, "单笔保证金超过上限", {}
        min_notional = float(((market_limits.get("cost") or {}).get("min") or 5))
        if entry * qty < min_notional:
            return False, f"下单金额低于最小名义价值: {min_notional}", {}

        fees = entry * qty * fee_rate
        slippage = entry * qty * slippage_rate
        position_risk = risk_per_unit * qty
        if position_risk > risk_budget:
            return False, "单笔真实风险超过上限", {}

        return True, "ok", {
            "entry": entry,
            "stop_loss": stop,
            "take_profit": take,
            "qty": qty,
            "rr": rr,
            "estimated_fee": fees,
            "estimated_slippage": slippage,
            "notional": entry * qty,
        }
