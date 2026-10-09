def fix():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    broken_str = """            if bot.pending_orders:
            try:
            # Procesar Mallas"""
    
    fixed_str = """            try:
                # Procesar Mallas"""
                
    content = content.replace(broken_str, fixed_str)
    
    # Also we need to fix the indentation of the try block content
    # Wait, it's easier to just strip the `if bot.pending_orders:` entirely and leave it as is if there's no try.
    # The current code has `manage_pending_limit_orders(bot, prices)` inside the try? No, my injection script didn't indent it.
    
    # Let's just fix it using regex to reconstruct the block.
    pass

import re
def fix2():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Just remove `if bot.pending_orders:` and `try:` completely if we don't need it.
    content = content.replace("            if bot.pending_orders:\n            try:\n            # Procesar Mallas (Grid Engine)", "            # Procesar Mallas (Grid Engine)")
    
    # And remove the except block:
    content = content.replace("            manage_pending_limit_orders(bot, prices)\n                except Exception as err:\n                    print(f\"  [Error Límite] {err}\", flush=True)", "            manage_pending_limit_orders(bot, prices)")
    
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    fix2()
