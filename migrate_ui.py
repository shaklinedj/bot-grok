import re

def migrate_ui():
    with open("dashboard_spa.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Inject grids container into HTML
    grids_html = """
    <!-- Mallas Activas (Grid Trading) -->
    <div class="space-y-3 mt-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm uppercase font-black tracking-wider text-purple-400 flex items-center gap-2">
          <span>🕸️</span>
          <span>Mallas Cuantitativas Activas</span>
        </h2>
      </div>
      <div id="grids-container" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Inyectado por JS -->
      </div>
    </div>
    """
    
    if "Mallas Cuantitativas Activas" not in content:
        # Insert before positions section
        content = content.replace("<!-- Posiciones Activas Vivas (Live Cards) -->", grids_html + "\n    <!-- Posiciones Activas Vivas (Live Cards) -->")

    # Inject JS function
    render_grids_js = """
    function renderGrids(grids) {
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
        const buys = lines.filter(l => l.side === 'buy' && l.active).length;
        const sells = lines.filter(l => l.side === 'sell' && l.active).length;
        
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
          
          <div class="grid grid-cols-2 gap-2 text-xs font-mono bg-[#0f111a] p-2 rounded border border-gray-800">
            <div class="text-center">
              <div class="text-gray-500">Compras Esperando</div>
              <div class="font-bold text-cyan-400">${buys} líneas</div>
            </div>
            <div class="text-center border-l border-gray-800">
              <div class="text-gray-500">Ventas (Hold)</div>
              <div class="font-bold text-rose-400">${sells} líneas</div>
            </div>
          </div>
          <div class="mt-2 text-[10px] text-gray-500 flex justify-between">
            <span>Paso: ${(Number(g.step_pct)*100).toFixed(2)}%</span>
            <span>Inversión: $${Number(g.capital_total).toFixed(2)}</span>
          </div>
        </div>`;
      }
      container.innerHTML = html;
    }
    """
    
    if "function renderGrids" not in content:
        content = content.replace("function renderPositions(positions) {", render_grids_js + "\n    function renderPositions(positions) {")

    # Call renderGrids in updateUI
    if "renderGrids(data.grids" not in content:
        content = content.replace("renderPositions(posList);", "renderPositions(posList);\n      renderGrids(data.grids || []);")

    with open("dashboard_spa.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    migrate_ui()
    print("UI Migration executed.")
