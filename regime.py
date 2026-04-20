def detect_regime(obi, cme_delta, distance_to_strike, velocity, rsi_1h):
    if distance_to_strike < 15:
        return "DEAD_ZONE", "NONE", 0, f"Distance ${distance_to_strike:.2f} < $15"
    
    if rsi_1h < 25:
        return "RSI_EXTREME", "UP", 80, f"1H RSI {rsi_1h:.1f} < 25 - Fade to UP"
    if rsi_1h > 75:
        return "RSI_EXTREME", "DOWN", 80, f"1H RSI {rsi_1h:.1f} > 75 - Fade to DOWN"
    
    if obi > 0.60:
        if velocity > 0:
            return "WHALE_REGIME", "UP", 85, f"OBI {obi:.2f} > 0.60 + velocity {velocity:.1f} > 0"
        else:
            return "WHALE_REGIME", "NONE", 0, f"OBI {obi:.2f} > 0.60 but velocity {velocity:.1f} conflicting"
    
    if obi < -0.50:
        if velocity < 0:
            return "WHALE_REGIME", "DOWN", 85, f"OBI {obi:.2f} < -0.50 + velocity {velocity:.1f} < 0"
        else:
            return "WHALE_REGIME", "NONE", 0, f"OBI {obi:.2f} < -0.50 but velocity {velocity:.1f} conflicting"
    
    if cme_delta < -30:
        return "GRAVITY_REGIME", "DOWN", 75, f"CME {cme_delta:.1f} < -30"
    
    return "CHAOS_REGIME", "NONE", 0, "No clear regime detected"
