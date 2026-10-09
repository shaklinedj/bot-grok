import re

def fix():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    broken_try = """            if bot.pending_orders:
                try:
                    
            # Procesar Mallas (Grid Engine)"""
            
    fixed_try = """
            # Procesar Mallas (Grid Engine)"""

    if broken_try in content:
        content = content.replace(broken_try, fixed_try)

    # I also need to put manage_pending_limit_orders back correctly!
    # Where is manage_pending_limit_orders now?
    # I injected it at the end of the grid_processing_code.
    # Let's fix the whole block.
    
    # Actually, the old code had an `except Exception as err:` right below it.
    
def fix2():
    with open("paper_trading_agent.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    # The current state has:
    '''
            if bot.pending_orders:
                try:
                    
            # Procesar Mallas (Grid Engine)
            ...
            manage_pending_limit_orders(bot, prices)
                except Exception as err:
                    print(f"  [Error Límite] {err}", flush=True)
    '''
    # We want to fix it.
    
    import re
    # Just replace the broken try block with a proper try block
    content = content.replace("                try:\n                    \n            # Procesar Mallas", "            try:\n            # Procesar Mallas")
    
    with open("paper_trading_agent.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    fix2()
