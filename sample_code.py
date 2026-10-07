def calculate_discount(price: float, discount_percent: float) -> float:
    """
    Calculate the discounted price given a base price and a discount percentage.
    """
    if price < 0:
        raise ValueError("Price cannot be negative")
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Discount percentage must be between 0 and 100")
    return round(price * (1.0 - discount_percent / 100.0), 2)
