import re

def update_live_state_grids():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    old_line = '"grids": [g.to_dict() for g in bot.grids.values() if g.active],'
    new_line = '"grids": [{**g.to_dict(), "current_price": prices.get(g.symbol, g.grid_lower)} for g in bot.grids.values() if g.active],'
    
    if old_line in content:
        content = content.replace(old_line, new_line)
        
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    update_live_state_grids()
