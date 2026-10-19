"""Tests for app.calc. Run with: python tests/test_calc.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.calc import total


def test_total():
    assert total([1, 2, 3]) == 6, f"expected 6, got {total([1, 2, 3])}"


def test_total_empty():
    assert total([]) == 0


def test_total_single():
    assert total([5]) == 5


if __name__ == "__main__":
    test_total()
    test_total_empty()
    test_total_single()
    print("all tests passed")
