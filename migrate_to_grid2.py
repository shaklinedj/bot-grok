import re

def migrate():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()

    grid_processing_code = """
            # Procesar Mallas (Grid Engine)
            for sym, grid in list(bot.grids.items()):
                if not grid.active:
                    continue
                curr_p = prices.get(sym)
                if not curr_p:
                    continue
                
                # Check lines
                for line in grid.lines:
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

            manage_pending_limit_orders(bot, prices)"""

    if "# Procesar Mallas (Grid Engine)" not in content:
        content = content.replace("manage_pending_limit_orders(bot, prices)", grid_processing_code)
        
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    migrate()
    print("Migration script executed.")
