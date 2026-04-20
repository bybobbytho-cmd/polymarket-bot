def should_execute(regime, trade_direction, price_position, distance_to_strike, confidence):
    if distance_to_strike > 150 and trade_direction != "NONE":
        return True, trade_direction, 1.0, f"EXTREME DISTANCE: ${distance_to_strike:.0f} - trust regime"
    
    if regime == "DEAD_ZONE":
        return False, None, 0, "Dead zone - no trade"
    
    if regime == "RSI_EXTREME":
        return True, trade_direction, 1.0, f"RSI extreme fade to {trade_direction}"
    
    if regime == "WHALE_REGIME" and trade_direction != "NONE":
        size_mult = 0.8 if confidence < 80 else 1.0
        return True, trade_direction, size_mult, f"Whale regime: {trade_direction} with {confidence}% confidence"
    
    if regime == "GRAVITY_REGIME":
        if price_position < 0:
            return True, "DOWN", 0.8, f"Gravity regime: DOWN with price ${abs(price_position):.0f} below strike"
        else:
            return False, None, 0, f"Gravity regime but price above strike (${price_position:.0f})"
    
    return False, None, 0, "Chaos regime - no clear signal"
