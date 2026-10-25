"""Loan math used for comparing offers and writing the trade-off disclosure."""


def monthly_payment(amount, apr, months):
    r = apr / 100 / 12
    if r == 0:
        return amount / months
    return amount * r / (1 - (1 + r) ** -months)


def total_cost(t):
    """Total the borrower pays back: payments plus any fee."""
    return monthly_payment(t.amount, t.apr, t.term_months) * t.term_months + t.fee


def interest_cost(t):
    return total_cost(t) - t.amount


def cost_per_dollar(t):
    """Comparable across different amounts: dollars of interest+fees per dollar borrowed."""
    return interest_cost(t) / t.amount if t.amount else float("inf")
