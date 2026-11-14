"""Generate CSV ledgers and per-strategy Markdown from canonical paper state."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGERS = ROOT / "data" / "ledgers"
PAGES = ROOT / "docs" / "bots"
FIELDS = ("slug", "side", "type", "status", "placed_at", "filled_at", "cancelled_at",
          "settled_at", "price", "shares", "cost", "reserved", "edge", "won", "payout", "pnl",
          "trade_placed_at", "exit_price", "close_reason", "fee")


def write_csv(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def export(state):
    PAGES.mkdir(parents=True, exist_ok=True)
    for name, account in sorted(state["accounts"].items()):
        orders = account.get("orders", [])
        trades = account.get("trades", [])
        write_csv(LEDGERS / (name + "-orders.csv"), orders)
        write_csv(LEDGERS / (name + "-trades.csv"), trades)
        settled = [t for t in trades if t["status"] == "settled"]
        wins = sum(bool(t.get("won")) for t in settled)
        losses = len(settled)-wins
        pnl = sum(t.get("pnl", 0) for t in settled)
        reserved = sum(o.get("reserved", 0) for o in orders if o["status"] == "open")
        metric = state.get("forecast_metrics", {}).get(name, {})
        markets = metric.get("markets", 0)
        brier = "%.4f" % (metric["brier_sum"]/markets) if markets else "—"
        delta = "%+.4f" % ((metric["market_brier_sum"]-metric["brier_sum"])/markets) if markets else "—"
        fees = sum(o.get("fee", 0) or 0 for o in orders if o.get("status") == "filled")
        page = ["# " + name, "", "Paper account · simulated orders", "",
                "| Metric | Value |", "|---|---:|",
                "| Cash | $%.2f |" % account["cash"],
                "| Reserved | $%.2f |" % reserved,
                "| Realized P&L | $%+.2f |" % pnl,
                "| Settled wins / losses | %d / %d |" % (wins, losses),
                "| Open positions | %d |" % sum(t["status"] == "open" for t in trades),
                "| Pending orders | %d |" % sum(o["status"] == "open" for o in orders),
                "| Orders filled / placed | %d / %d |" % (sum(o["status"] == "filled" for o in orders), len(orders)),
                "| Recorded exit fees | $%.4f |" % fees,
                "| Brier (markets) | %s (%d) |" % (brier, markets),
                "| ΔBrier vs market | %s |" % delta, "",
                "[Order ledger](../../data/ledgers/" + name + "-orders.csv) · " +
                "[Trade ledger](../../data/ledgers/" + name + "-trades.csv) · [Overview](../../REPORT.md)", ""]
        if settled:
            page += ["```mermaid", "pie title Settled simulated trades",
                     '    "Wins" : %d' % wins, '    "Losses" : %d' % losses, "```", ""]
        page += ["## Results by market horizon", "",
                 "| Horizon | Closed trades | Realized P&L |",
                 "|---|---:|---:|"]
        for horizon in ("15m", "1h"):
            group = [t for t in settled if "-" + horizon + "-" in t.get("slug", "")]
            page.append("| %s | %d | $%+.2f |" %
                        (horizon, len(group), sum(t.get("pnl", 0) for t in group)))
        page += ["", "## Research", "",
                 "The shared research candidate is evaluated separately; it is not deployed to this account. "
                 "[Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)", "",
                 "Limit fills are estimates based on later observed book crossings; queue priority is unknown.", ""]
        (PAGES / (name + ".md")).write_text("\n".join(page), encoding="utf-8")
