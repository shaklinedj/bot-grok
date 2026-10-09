import re

def migrate_ui2():
    with open("dashboard_spa.py", "r", encoding="utf-8") as f:
        content = f.read()

    new_render_grids = """    function renderGrids(grids) {
      const container = document.getElementById('grids-container');
      if (!container) return;
      if (!grids || grids.length === 0) {
        container.innerHTML = `
          <div class="col-span-full card p-8 text-center border-dashed border-gray-800">
            <div class="text-3xl mb-2">🕸️</div>
            <div class="text-gray-300 font-bold">Sin Mallas Activas</div>
            <p class="text-xs text-gray-500 mt-1">El Arquitecto IA está buscando volatilidad en rangos.</p>
          </div>
        `;
        return;
      }
      
      let html = '';
      for (const g of grids) {
        const lines = g.lines || [];
        const buys = lines.filter(l => l.side === 'buy' && l.active).sort((a,b) => b.price - a.price); // Descending
        const sells = lines.filter(l => l.side === 'sell' && l.active).sort((a,b) => b.price - a.price); // Descending
        const currentPrice = g.current_price || g.grid_lower;
        
        // Generar filas para la tabla de la malla
        let linesHtml = '';
        
        // Ventas (por encima del precio actual)
        for (const l of sells) {
            const dist = ((l.price - currentPrice) / currentPrice * 100).toFixed(2);
            linesHtml += `
            <div class="flex justify-between items-center py-1 border-b border-gray-800 text-[11px] font-mono">
                <span class="text-rose-400 font-bold">SELL LIMIT</span>
                <span class="text-white">$${Number(l.price).toFixed(4)}</span>
                <span class="text-gray-500">Dist: +${dist}%</span>
            </div>`;
        }
        
        // Precio Actual
        linesHtml += `
            <div class="flex justify-between items-center py-1.5 my-1 bg-blue-900/20 border border-blue-500/30 rounded px-2 text-xs font-mono font-bold">
                <span class="text-blue-400">PRECIO ACTUAL</span>
                <span class="text-white">$${Number(currentPrice).toFixed(4)}</span>
                <span class="text-blue-400">►</span>
            </div>`;
            
        // Compras (por debajo del precio actual)
        for (const l of buys) {
            const dist = ((currentPrice - l.price) / currentPrice * 100).toFixed(2);
            linesHtml += `
            <div class="flex justify-between items-center py-1 border-b border-gray-800 text-[11px] font-mono">
                <span class="text-cyan-400 font-bold">BUY LIMIT</span>
                <span class="text-white">$${Number(l.price).toFixed(4)}</span>
                <span class="text-gray-500">Dist: -${dist}%</span>
            </div>`;
        }
        
        html += `
        <div class="card p-4 border-l-4 border-l-purple-500 relative overflow-hidden group hover:border-l-purple-400 transition-colors">
          <div class="flex justify-between items-start mb-3">
            <div>
              <div class="flex items-center gap-2">
                <span class="text-lg font-black text-white tracking-tight">${g.symbol}</span>
                <span class="text-[10px] bg-purple-500/20 text-purple-300 font-mono font-bold px-1.5 py-0.5 rounded border border-purple-500/30">GRID ACTIVA</span>
              </div>
              <div class="text-xs font-mono text-gray-400 mt-1">
                Piso: <span class="text-white">${Number(g.grid_lower).toFixed(4)}</span> | Techo: <span class="text-white">${Number(g.grid_upper).toFixed(4)}</span>
              </div>
            </div>
            <div class="text-right">
              <div class="text-xs text-gray-500">PnL Cosechado</div>
              <div class="text-lg font-bold font-mono text-emerald-400">+$${Number(g.realized_pnl).toFixed(2)}</div>
            </div>
          </div>
          
          <div class="grid grid-cols-2 gap-2 text-xs font-mono bg-[#0f111a] p-2 rounded border border-gray-800 mb-3">
            <div class="text-center">
              <div class="text-gray-500">Compras Esperando</div>
              <div class="font-bold text-cyan-400">${buys.length} líneas</div>
            </div>
            <div class="text-center border-l border-gray-800">
              <div class="text-gray-500">Ventas (Hold)</div>
              <div class="font-bold text-rose-400">${sells.length} líneas</div>
            </div>
          </div>
          
          <!-- Escalones de la Malla -->
          <div class="bg-[#0f111a] rounded border border-gray-800 p-2 max-h-48 overflow-y-auto custom-scrollbar">
            ${linesHtml}
          </div>
          
          <div class="mt-3 text-[10px] text-gray-500 flex justify-between">
            <span>Paso entre líneas: ${(Number(g.step_pct)*100).toFixed(2)}%</span>
            <span>Inversión Total: $${Number(g.capital_total).toFixed(2)}</span>
          </div>
        </div>`;
      }
      container.innerHTML = html;
    }"""
    
    # We replace the old renderGrids function
    pattern = re.compile(r'    function renderGrids\(grids\) \{.*?(?=    function renderPositions)', re.DOTALL)
    content = pattern.sub(new_render_grids + "\n", content)
    
    with open("dashboard_spa.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    migrate_ui2()
