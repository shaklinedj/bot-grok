def fix_equity():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()

    new_equity_logic = """    def get_equity(self, prices: Dict[str, float]) -> float:
        # Equity = Efectivo libre + valor de longs + PnL flotante de shorts + Valor de las Mallas
        equity = self.cash + self.get_holdings_value(prices)
        for sym, pos in self.longs.items():
            if pos.active and getattr(pos, "side", "long") == "short":
                curr_p = prices.get(sym, pos.entry_price)
                if curr_p and curr_p > 0:
                    short_flot_pnl = (pos.entry_price - curr_p) * pos.amount
                    equity += (pos.capital_allocated + short_flot_pnl)
                    
        # Calcular valor bloqueado y flotante en mallas activas
        for sym, grid in self.grids.items():
            if not grid.active:
                continue
            curr_p = prices.get(sym, grid.grid_upper)
            for line in grid.lines:
                if not line["active"]:
                    continue
                if line["side"] == "buy":
                    # Dinero retenido en orden de compra
                    equity += (line["price"] * line["amount"])
                elif line["side"] == "sell":
                    # Valor actual de la moneda que estamos holdeando para vender
                    equity += (line["amount"] * curr_p)
                    
        return equity"""

    import re
    # Match the old get_equity method
    pattern = re.compile(r'    def get_equity.*?return equity', re.DOTALL)
    content = pattern.sub(new_equity_logic, content, count=1)
    
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    fix_equity()
