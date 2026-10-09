def fix_grid_math():
    with open("agent_committee.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update the prompt to ask for amplitud_malla_atr instead of absolute prices
    old_roles = "2. [ARQUITECTO DE MALLAS]: Diagnostica la estructura técnica real. Diseña el Precio Techo (grid_upper) y Precio Piso (grid_lower) basándose en soportes/resistencias recientes y ATR. (Asegurar que grid_upper > {price} y grid_lower < {price})."
    new_roles = "2. [ARQUITECTO DE MALLAS]: Diseña la AMPLITUD de la malla usando el ATR como medida. Elige un multiplicador `amplitud_malla_atr` (ej. 1.0 a 3.0). Malla estrecha (1.0x ATR) cosecha rápido pero se sale del rango fácil. Malla ancha (3.0x ATR) dura más pero cosecha lento."
    content = content.replace(old_roles, new_roles)
    
    old_json = '"grid_upper": float (precio límite superior de la malla),\n  "grid_lower": float (precio límite inferior de la malla),'
    new_json = '"amplitud_malla_atr": float (multiplicador de amplitud, ej. 1.5),'
    content = content.replace(old_json, new_json)

    # 2. Update the parser
    old_parser = '                grid_upper = float(parsed.get("grid_upper", 0.0))\n                grid_lower = float(parsed.get("grid_lower", 0.0))\n                grid_lines = int(parsed.get("grid_lines", 0))\n\n                # Validación de seguridad de la malla\n                if decision_clean == "APROBADO":\n                    if grid_upper <= price or grid_lower >= price or grid_lines < 2:\n                        decision_clean = "RECHAZADO"\n                        parsed["razon_clave"] = "Malla inválida (precios ilógicos o líneas < 2)"'
                        
    new_parser = '''                amplitud_malla_atr = float(parsed.get("amplitud_malla_atr", 2.0))
                grid_lines = int(parsed.get("grid_lines", 0))
                
                # Calcular matemáticamente el grid exacto basado en el ATR real de la moneda
                atr_pct = analysis.get('atr_pct', 2.0)
                range_pct = (atr_pct / 100.0) * amplitud_malla_atr
                
                grid_upper = price * (1 + range_pct)
                grid_lower = price * (1 - range_pct)

                # Validación de seguridad de la malla
                if decision_clean == "APROBADO":
                    if grid_lines < 2:
                        decision_clean = "RECHAZADO"
                        parsed["razon_clave"] = "Líneas < 2"
                    else:
                        step_size_pct = ((grid_upper - grid_lower) / grid_lower) / (grid_lines - 1) * 100
                        if step_size_pct < 0.4:
                            decision_clean = "RECHAZADO"
                            parsed["razon_clave"] = f"Paso muy estrecho ({step_size_pct:.2f}%) no cubre fees"
                        elif step_size_pct > 3.0:
                            decision_clean = "RECHAZADO"
                            parsed["razon_clave"] = f"Paso muy ancho ({step_size_pct:.2f}%) ineficiente"
                        '''
    content = content.replace(old_parser, new_parser)

    with open("agent_committee.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    fix_grid_math()
