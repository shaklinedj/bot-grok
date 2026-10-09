import re

def center_grid():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()

    old_deployment = """                                    # Crear lineas de compra por debajo del precio actual
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
                                            print(f"  ⚠️ [MALLA CANCELADA] Capital por línea (${cap_per_line:.2f}) es menor al mínimo de $5.", flush=True)"""

    new_deployment = """                                    # Malla Centrada (Neutral Grid Pionex-style)
                                    cap_per_line = adjusted_capital / grid_lines
                                    if cap_per_line >= 5.0:
                                        lines = []
                                        total_cash_needed = 0.0
                                        buys_count = 0
                                        sells_count = 0
                                        current_price = best_candidate["price"]
                                        
                                        p = grid_lower
                                        while p <= grid_upper + (step_size * 0.1): # Tolerancia de flotantes
                                            if p < current_price:
                                                # Orden Límite de Compra
                                                lines.append({"price": p, "side": "buy", "amount": cap_per_line / p, "active": True})
                                                total_cash_needed += cap_per_line
                                                buys_count += 1
                                            else:
                                                # Orden Límite de Venta (Requiere compra a mercado inicial)
                                                amount = cap_per_line / p
                                                # Compramos a mercado al precio actual para poder colocar la venta límite
                                                cost = amount * current_price * (1 + FEE_RATE)
                                                lines.append({"price": p, "side": "sell", "amount": amount, "active": True})
                                                total_cash_needed += cost
                                                sells_count += 1
                                            p += step_size
                                            
                                        if bot.cash >= total_cash_needed:
                                            new_grid = GridPosition(
                                                grid_id=f"grid_{int(time.time()*1000)}",
                                                symbol=sym,
                                                grid_upper=grid_upper,
                                                grid_lower=grid_lower,
                                                grid_lines=grid_lines,
                                                step_pct=step_pct,
                                                capital_total=total_cash_needed,
                                                capital_per_line=cap_per_line,
                                                lines=lines
                                            )
                                            bot.grids[sym] = new_grid
                                            bot.cash -= total_cash_needed
                                            print(f"  🕸️ [MALLA CENTRADA DESPLEGADA] {buys_count} Compras abajo, {sells_count} Ventas arriba preparadas.", flush=True)
                                        else:
                                            print(f"  ⚠️ [MALLA CANCELADA] Saldo insuficiente para armar la malla centrada.", flush=True)
                                    else:
                                        print(f"  ⚠️ [MALLA CANCELADA] Capital por línea (${cap_per_line:.2f}) es menor al mínimo de $5.", flush=True)"""

    content = content.replace(old_deployment, new_deployment)
    
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    center_grid()
