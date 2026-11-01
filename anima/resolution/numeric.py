"""Exact decimal interpretation and rational arithmetic, without context rounding.

Finite floats supplied by callers mean their shortest decimal representation.
Frontend decimal literals arrive as Decimal and never pass through float.
Non-terminating decimal results are explicitly unsupported rather than rounded.
"""

from decimal import Decimal
from fractions import Fraction
import math


def is_number(value):
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return isinstance(value, Decimal) and value.is_finite()


def rational(value):
    if not is_number(value):
        raise ValueError("Expected a finite numeric value")
    return Fraction(Decimal(str(value))) if type(value) is float else Fraction(value)


def decimal_result(value):
    """Convert an exact rational to an exact finite decimal (or an integer)."""
    if value.denominator == 1:
        return value.numerator
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("Non-terminating decimal result")
    scale = max(twos, fives)
    coefficient = value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    return Decimal((int(coefficient < 0), digits, -scale))
