# tests/test_parser.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.parse_sms import MpesaParser

parser = MpesaParser()

def test_amount_extraction_ksh():
    body = "Confirmed. Ksh1,500.00 paid to NAIVAS on 1/6/24"
    assert parser._extract_amount(body) == 1500.00

def test_amount_extraction_with_spaces():
    body = "Ksh 250.00 sent to John Doe"
    assert parser._extract_amount(body) == 250.00

def test_amount_none_when_missing():
    body = "Your MPESA PIN has been changed successfully."
    assert parser._extract_amount(body) is None

def test_type_credit():
    body = "You have received Ksh500 from JOHN DOE"
    assert parser._determine_type(body) == 'credit'

def test_type_payment():
    body = "Confirmed. Ksh200 paid to JAVA HOUSE"
    assert parser._determine_type(body) == 'payment'

def test_type_withdrawal():
    body = "Confirmed. Ksh1000 withdrew from Agent"
    assert parser._determine_type(body) == 'withdrawal'

def test_type_airtime():
    body = "Confirmed. Ksh50 airtime purchase"
    assert parser._determine_type(body) == 'airtime'

def test_type_transfer():
    body = "Confirmed. You have transferred Ksh300 to JANE"
    assert parser._determine_type(body) == 'transfer'

def test_balance_extraction():
    body = "Ksh500 paid. New balance is Ksh12,345.00"
    assert parser._extract_balance(body) == 12345.00

def test_transaction_id_extraction():
    body = "ABC1234567 Confirmed. Ksh100 paid to MERCHANT"
    tx_id = parser._extract_transaction_id(body)
    assert tx_id == "ABC1234567"

def test_phone_extraction():
    body = "You have received Ksh100 from 0712345678"
    assert parser._extract_phone(body) == "0712345678"

def test_category_food():
    body = "Ksh500 paid to JAVA HOUSE WESTGATE"
    cat = parser._categorize(body, "Java House")
    assert cat == 'food'

def test_category_transport():
    body = "Ksh150 paid to UBER KENYA"
    cat = parser._categorize(body, "Uber")
    assert cat == 'transport'

def test_category_utilities():
    body = "Ksh1000 paid to KPLC PREPAID"
    cat = parser._categorize(body, "Kenya Power")
    assert cat == 'utilities'

def test_category_other():
    body = "Ksh500 paid to RANDOM UNKNOWN XYZ"
    cat = parser._categorize(body, "Random Unknown")
    assert cat == 'other'

def test_is_mpesa_true():
    assert parser._is_mpesa("Confirmed. Ksh100 paid via M-PESA") is True

def test_is_mpesa_false():
    assert parser._is_mpesa("Your OTP is 123456") is False