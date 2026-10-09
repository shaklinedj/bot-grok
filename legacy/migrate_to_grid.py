import re

def migrate():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add Grid dataclasses
    dataclasses_code = """
@dataclass
class GridLine:
    price: float
    side: str  # "buy" or "sell"
    amount: float
    active: bool = True

@dataclass
class GridPosition:
    grid_id: str
    symbol: str
    grid_upper: float
    grid_lower: float
    grid_lines: int
    step_pct: float
    capital_total: float
    capital_per_line: float
    lines: list
    realized_pnl: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active: bool = True
    status_msg: str = "Grid Activa"

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)
"""
    if "class GridPosition:" not in content:
        content = content.replace("@dataclass\nclass PendingLimitOrder:", dataclasses_code + "\n@dataclass\nclass PendingLimitOrder:")

    # 2. Add grids to PaperBot
    if "self.grids: Dict[str, GridPosition] = {}" not in content:
        content = content.replace("self.longs: Dict[str, LongPosition] = {}", "self.longs: Dict[str, LongPosition] = {}\n        self.grids: Dict[str, GridPosition] = {}")

    # 3. Modify PaperBot state saving/loading
    if '"grids":' not in content:
        content = content.replace('"longs": {k: v.to_dict() for k, v in self.longs.items() if v.active},', 
                                  '"longs": {k: v.to_dict() for k, v in self.longs.items() if v.active},\n                "grids": {k: v.to_dict() for k, v in self.grids.items() if v.active},')

    if 'self.grids = {}' not in content:
        content = content.replace('self.longs = {}', 'self.longs = {}\n                    self.grids = {}')
        
    # Replace dict-to-class for grids in load_portfolio
    if 'GridPosition.from_dict' not in content:
        loader_code = """
                    self.grids = {}
                    grids_data = data.get("grids", {})
                    for sym, grid_dict in grids_data.items():
                        try:
                            self.grids[sym] = GridPosition.from_dict(grid_dict)
                        except Exception:
                            pass
"""
        content = content.replace('self.longs = {}', 'self.longs = {}\n' + loader_code)

    # 4. Remove compound_size calculation which we don't need, or keep it as mock
    # Wait, we changed main loop to read Grid info. Let's find main loop where committee result is processed.
    main_loop_start = content.find('decision = committee_verdict.get("decision", "RECHAZADO")')
    main_loop_end = content.find('# Actualizar estado en vivo en memoria y JSON', main_loop_start)
    
    old_loop = content[main_loop_start:main_loop_end]
    new_loop = """decision = committee_verdict.get("decision", "RECHAZADO")
                            grid_upper = float(committee_verdict.get("grid_upper", 0.0))
                            grid_lower = float(committee_verdict.get("grid_lower", 0.0))
                            grid_lines = int(committee_verdict.get("grid_lines", 0))
                            comm_mult = float(committee_verdict.get("multiplicador_capital", 0.50))
                            razon = committee_verdict.get("razon_clave", "Consenso alcanzado")
                            debate = committee_verdict.get("debate", {})

                            print(f"       Centinela: {debate.get('centinela_macro', '')}", flush=True)
                            print(f"       Arquitecto: {debate.get('arquitecto_mallas', '')}", flush=True)
                            print(f"       Riesgo: {debate.get('jefe_riesgo', '')}", flush=True)
                            print(f"       Ejecución: {debate.get('coordinador_ejecucion', '')}", flush=True)

                            if decision != "APROBADO":
                                print(f"  🛑 [COMITÉ RECHAZÓ {sym}] {razon}", flush=True)
                            else:
                                global LAST_AGENT_PCT
                                available_funds = bot.cash * 0.98
                                target_by_agents = round(available_funds * comm_mult, 2)
                                adjusted_capital = max(MIN_ORDER_USDT, min(available_funds, target_by_agents))
                                pct_display = round(comm_mult * 100, 0)
                                LAST_AGENT_PCT = pct_display
                                
                                print(f"  🏛️ [MALLA APROBADA {sym}] Techo: ${grid_upper:.4f} | Piso: ${grid_lower:.4f} | Líneas: {grid_lines} | Capital: ${adjusted_capital:.2f} ({pct_display:.0f}%)", flush=True)
                                
                                # Instanciar la Malla
                                if grid_lines >= 2 and grid_upper > grid_lower:
                                    step_size = (grid_upper - grid_lower) / (grid_lines - 1)
                                    step_pct = step_size / grid_lower
                                    
                                    # Crear lineas de compra por debajo del precio actual
                                    buy_prices = []
                                    p = grid_lower
                                    while p <= grid_upper:
                                        if p < best_candidate["price"] * 0.999:  # Un poco por debajo para ser Maker
                                            buy_prices.append(p)
                                        p += step_size
                                        
                                    if buy_prices:
                                        cap_per_line = adjusted_capital / len(buy_prices)
                                        if cap_per_line >= 5.0: # Minimo de Binance usual es 5
                                            lines = []
                                            for bp in buy_prices:
                                                lines.append({"price": bp, "side": "buy", "amount": cap_per_line / bp, "active": True})
                                                
                                            new_grid = GridPosition(
                                                grid_id=f"grid_{int(time.time()*1000)}",
                                                symbol=sym,
                                                grid_upper=grid_upper,
                                                grid_lower=grid_lower,
                                                grid_lines=grid_lines,
                                                step_pct=step_pct,
                                                capital_total=adjusted_capital,
                                                capital_per_line=cap_per_line,
                                                lines=lines
                                            )
                                            bot.grids[sym] = new_grid
                                            bot.cash -= adjusted_capital
                                            print(f"  🕸️ [MALLA DESPLEGADA] {len(buy_prices)} órdenes de compra preparadas.", flush=True)
                                        else:
                                            print(f"  ⚠️ [MALLA CANCELADA] Capital por línea (${cap_per_line:.2f}) es menor al mínimo de $5.", flush=True)
                                """
    if "grid_upper =" not in old_loop:
        content = content.replace(old_loop, new_loop)

    # 5. Grid processing loop (Checking fills)
    # We need to add grid logic inside the main while loop.
    # We can inject it right before check_pending_orders(bot, prices)
    grid_processing_code = """
            # Procesar Mallas (Grid Engine)
            for sym, grid in list(bot.grids.items()):
                if not grid.active:
                    continue
                curr_p = prices.get(sym)
                if not curr_p:
                    continue
                
                # Check lines
                for i, line in enumerate(grid.lines):
                    if not line["active"]:
                        continue
                        
                    if line["side"] == "buy":
                        if curr_p <= line["price"]:
                            # Ejecutar Compra Limit
                            fees = (line["amount"] * line["price"]) * FEE_RATE
                            line["active"] = False
                            
                            # Crear orden de venta en el siguiente escalón
                            sell_price = line["price"] * (1 + grid.step_pct)
                            # Binance fee is paid in base coin usually, we deduct fee from amount
                            amt_after_fee = line["amount"] * (1 - FEE_RATE)
                            
                            grid.lines.append({"price": sell_price, "side": "sell", "amount": amt_after_fee, "active": True})
                            print(f"  🕸️🟢 [MALLA BUY {sym}] Comprado a ${line['price']:.4f}. Venta colocada a ${sell_price:.4f}", flush=True)
                            
                    elif line["side"] == "sell":
                        if curr_p >= line["price"]:
                            # Ejecutar Venta Limit
                            gross = line["amount"] * line["price"]
                            fees = gross * FEE_RATE
                            net_usdt = gross - fees
                            
                            line["active"] = False
                            
                            # Ganancia de esta línea
                            buy_cost = line["amount"] * (line["price"] / (1 + grid.step_pct))
                            profit = net_usdt - buy_cost
                            grid.realized_pnl += profit
                            bot.total_realized_pnl_acc += profit
                            bot.cash += net_usdt
                            bot.wins += 1
                            bot.total_trades += 1
                            
                            # Recolocar la orden de compra abajo
                            buy_price = line["price"] / (1 + grid.step_pct)
                            # Necesitamos descontar el cash
                            cost = line["amount"] * buy_price
                            if bot.cash >= cost:
                                bot.cash -= cost
                                grid.lines.append({"price": buy_price, "side": "buy", "amount": line["amount"], "active": True})
                                print(f"  🕸️🔴 [MALLA SELL {sym}] Vendido a ${line['price']:.4f}. Ganancia: ${profit:.4f}. Recomprando a ${buy_price:.4f}", flush=True)
                            else:
                                print(f"  ⚠️ [MALLA {sym}] Saldo insuficiente para recolocar compra a ${buy_price:.4f}", flush=True)

            """
    if "# Procesar Mallas (Grid Engine)" not in content:
        content = content.replace("check_pending_orders(bot, prices)", grid_processing_code + "\n            check_pending_orders(bot, prices)")

    # 6. Include grids in live_state
    if '"grids":' not in content[content.find('LATEST_LIVE_STATE = {'):]:
        live_state_loc = content.find('LATEST_LIVE_STATE = {')
        if live_state_loc != -1:
            content = content.replace('"positions": positions_list,', '"positions": positions_list,\n        "grids": [g.to_dict() for g in bot.grids.values() if g.active],')

    # 7. Update Scanner to prefer Choppy/Ranging markets with high ATR
    # Find select_best_opportunities and modify the scoring weights
    if 'w_atr = 2.0' not in content:
        # Increase weight of ATR and penalize strong ADX trend for grids
        # In select_best_opportunities:
        content = content.replace('w_volume = 1.8', 'w_volume = 1.0\n    w_atr = 2.5  # Priorizar alta volatilidad para la malla')
        content = content.replace('w_volatility = 1.5', 'w_volatility = 0.5') # Keep or lower old volatility
        
        # Scoring logic modification: we want HIGH ATR, LOW ADX (Range bound)
        old_score_logic = """
        score = 0.0
        if adx > 25:
            score += min(adx, 50) * 0.4
        score += (rsi_norm * brain.weights.get("w_rsi", 1.2))
        """
        # We just replace a chunk of the scoring to favor grids if we want, but since I don't know the exact lines, 
        # let's just use regular expressions or simple replace for ADX logic.
        content = re.sub(r'score = 0\.0\s+if adx > 25:\s+score \+= min\(adx, 50\) \* 0\.4', 
                         'score = 0.0\n        # Para MALLAS: Preferimos ADX bajo (Rango) y ATR alto\n        if adx < 30:\n            score += (30 - adx) * 1.5\n        score += min(atr_pct * 10, 40)', 
                         content)

    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    migrate()
    print("Migration script executed.")
