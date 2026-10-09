"""The NF-e access key must follow the official 44-digit layout and módulo-11 rule."""
from datetime import datetime

from app.services.invoices import build_access_key, is_valid_access_key, mod11_check_digit


def test_mod11_hand_computed_examples():
    zeros = "0" * 43
    assert mod11_check_digit(zeros[:-1] + "1") == "9"            # sum 1x2=2, 11-2 = 9
    assert mod11_check_digit(zeros[:-1] + "5") == "1"            # sum 10, 11-10 = 1
    assert mod11_check_digit(zeros[:-2] + "14") == "0"           # sum 1x3+4x2 = 11, remainder 0 -> 0
    assert mod11_check_digit(zeros[:-1] + "6") == "0"            # sum 12, remainder 1 -> 0
    # weights cycle 2..9 then restart at 2
    assert mod11_check_digit("0" * 35 + "1" + "0" * 7) == "2"    # 8th from right, weight 9
    assert mod11_check_digit("0" * 34 + "1" + "0" * 8) == "9"    # 9th from right, weight 2 again


def test_access_key_layout():
    key = build_access_key("SP", datetime(2026, 10, 9), "12345678000195", series=1, number=42,
                           numeric_code="87654321")
    assert len(key) == 44 and key.isdigit()
    assert key[0:2] == "35"                 # SP state code
    assert key[2:6] == "2610"               # year + month
    assert key[6:20] == "12345678000195"    # issuer CNPJ
    assert key[20:22] == "55"               # model 55 = NF-e
    assert key[22:25] == "001"              # series
    assert key[25:34] == "000000042"        # invoice number
    assert key[34] == "1"                   # normal emission
    assert key[35:43] == "87654321"         # numeric code
    assert is_valid_access_key(key)


def test_tampered_key_is_rejected():
    key = build_access_key("RJ", datetime(2026, 1, 1), "1" * 14, 1, 7, "11111111")
    wrong_dv = key[:43] + str((int(key[43]) + 1) % 10)
    assert not is_valid_access_key(wrong_dv)
