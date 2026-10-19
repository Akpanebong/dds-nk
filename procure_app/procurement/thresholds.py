from decimal import Decimal


DIRECT_PURCHASE_LIMIT = Decimal('200000.00')


def uses_direct_purchase(amount):
    return amount is not None and Decimal(amount) <= DIRECT_PURCHASE_LIMIT
