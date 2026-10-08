import pytest

from src.parse_sms import MpesaParser

SENT_P2P = (
    "AB12CD34EF Confirmed. Ksh1,500.00 sent to JANE  DOE 0712345678 on 3/10/24 at 12:40 PM. "
    "New M-PESA balance is Ksh2,340.50. Transaction cost, Ksh23.00.  Amount you can transact within the day is 498,500.00."
)
SENT_PAYBILL = (
    "AB12CD34EG Confirmed. Ksh300.00 sent to Equity Paybill Account for account 104308#offering on 4/10/24 at 8:24 AM "
    "New M-PESA balance is Ksh2,040.50. Transaction cost, Ksh5.00."
)
PAID_TILL = (
    "AB12CD34EH Confirmed. Ksh100.00 paid to Vision  wholesale & retail shop. on 5/10/24 at 5:53 PM."
    "New M-PESA balance is Ksh1,940.50. Transaction cost, Ksh0.00. Amount you can transact within the day is 499,900.00."
)
PAID_KPLC = (
    "AB12CD34EI Confirmed. Ksh500.00 sent to KPLC PREPAID for account 14200000 on 6/10/24 at 9:00 AM "
    "New M-PESA balance is Ksh1,440.50. Transaction cost, Ksh0.00."
)
RECEIVED = (
    "AB12CD34EJ Confirmed.You have received Ksh6,000.00 from JOHN  SMITH 0707***979 on 7/10/24 at 1:40 PM  "
    "New M-PESA balance is Ksh7,440.50. Earn interest daily on Ziidi MMF, Dial *334#"
)
RECEIVED_BANK = (
    "AB12CD34EK Confirmed.You have received Ksh10,000.00 from Equity Bulk Account 300600 on 8/10/24 at 7:00 AM "
    "New M-PESA balance is Ksh17,440.50.  Separate personal and business funds through Pochi la Biashara."
)
AIRTIME = (
    "AB12CD34EL confirmed.You bought Ksh20.00 of airtime on 9/10/24 at 7:00 PM.New M-PESA balance is Ksh17,420.50. "
    "Transaction cost, Ksh0.00. Amount you can transact within the day is 499,980.00."
)
WITHDRAW = (
    "AB12CD34EM Confirmed.on 18/8/25 at 8:40 AMWithdraw Ksh1,250.00 from 680846 - EDSON CONVEYORS  GOSHEN Accra Rd "
    "New M-PESA balance is Ksh645.10. Transaction cost, Ksh29.00. Amount you can transact within the day is 498,650.00."
)
DEPOSIT = (
    "AB12CD34EN Confirmed. On 6/6/25 at 7:01 PM Give Ksh100.00 cash to Turk Cell comms Ramesh Gautama road Off Ngara Rd "
    "New M-PESA balance is Ksh101.50. You can now access M-PESA via *334#"
)
REVERSAL_CREDIT = (
    "AB12CD34EO confirmed. Reversal of transaction AB12CD34XX has been successfully reversed  on 16/9/25  at 8:28 PM "
    "and Ksh30.00 is credited to your M-PESA account. New M-PESA account balance is Ksh1,605.10."
)
REVERSAL_DEBIT = (
    "AB12CD34EP confirmed. Reversal of transaction AB12CD34YY has been successfully reversed  on 31/7/26  at 9:10 PM "
    "and Ksh60.00 is debited from your M-PESA account. New M-PESA account balance is Ksh2,691.12."
)
CARD = (
    "AB12CD34EQ Confirmed. Ksh154.22 sent to M-PESA CARD for account GOOGLE *eFootball 2024   g.co/helppay#US "
    "on 2/2/26 at 3:00 PM New M-PESA balance is Ksh20.00. Transaction cost, Ksh0.00."
)

NON_TRANSACTIONS = [
    "AB12CD34ER Confirmed. Your account balance was: M-PESA Account : Ksh1,317.00 on 17/10/24 at 11:40 AM. Transaction cost, Ksh0.00.",
    "You have cancelled the transaction of Ksh50.00. Kindly note that if you cancel 5 times, you will be barred from using M-PESA HAKIKISHA.",
    "Failed. The till number entered is incorrect. Kindly enter the correct Till Number and try again.",
    "Failed, you have entered the wrong PIN. If forgotten please dial *334#.",
    "Dear customer, you do not have sufficient funds in your M-PESA account to pay Ksh186.30 to GOOGLE *eFootball 2024. Your M-PESA balance is Ksh13.50.",
    "Insufficient funds in your M-PESA account for this transaction, to register for Fuliza M-PESA service, Dial *334#OK",
    "Transaction failed, M-PESA cannot complete payment of Ksh20.00 to Equity Paybill Account. Please try again shortly.",
    "AB12CD34ES Confirmed. Fuliza M-PESA amount is Ksh 58.94. Interest charged Ksh 0.59. Total Fuliza M-PESA outstanding amount is Ksh 59.53 due on 05/03/25.",
    "AB12CD34ET  Confirmed. Ksh 59.53 from your M-PESA has been used to fully pay your outstanding Fuliza M-PESA. M-PESA balance is Ksh940.47.",
    "Dear Customer, the recipient has declined reversal transaction AB12CD34EU of Ksh1,150.00 on 16/9/25 at 9:41 PM. Your M-PESA balance is Ksh1,575.10.",
    "Invalid input. To complete the transaction of KSH60.00 please select 1 to SEND.",
    "M-PESA is currently unable to process your request. Please try again later.",
]


@pytest.fixture
def parser():
    return MpesaParser()


def test_sent_to_person(parser):
    tx = parser._parse_sms_text(SENT_P2P)
    assert tx['transaction_id'] == 'AB12CD34EF'
    assert tx['amount'] == 1500.0
    assert tx['balance'] == 2340.50
    assert tx['transaction_cost'] == 23.0
    assert tx['type'] == 'payment'
    assert tx['recipient'] == 'Jane Doe'
    assert tx['phone'] == '0712345678'
    assert tx['merchant_category'] == 'personal'


def test_sent_to_paybill_keeps_account_name_and_category(parser):
    tx = parser._parse_sms_text(SENT_PAYBILL)
    assert tx['recipient'] == 'Equity Paybill Account'
    assert tx['transaction_cost'] == 5.0
    assert tx['merchant_category'] == 'banking'
    assert tx['phone'] is None


def test_paid_to_till_with_ampersand(parser):
    tx = parser._parse_sms_text(PAID_TILL)
    assert tx['recipient'] == 'Vision Wholesale & Retail Shop'
    assert tx['type'] == 'payment'
    assert tx['merchant_category'] == 'shopping'


def test_utility_paybill(parser):
    tx = parser._parse_sms_text(PAID_KPLC)
    assert tx['recipient'] == 'Kplc Prepaid'
    assert tx['merchant_category'] == 'utilities'


def test_received_from_person_with_masked_phone(parser):
    tx = parser._parse_sms_text(RECEIVED)
    assert tx['type'] == 'credit'
    assert tx['amount'] == 6000.0
    assert tx['recipient'] == 'John Smith'
    assert tx['phone'] == '0707***979'
    assert tx['merchant_category'] == 'personal'


def test_received_from_bank(parser):
    tx = parser._parse_sms_text(RECEIVED_BANK)
    assert tx['type'] == 'credit'
    assert tx['recipient'] == 'Equity Bulk Account'
    assert tx['merchant_category'] == 'banking'


def test_airtime_purchase(parser):
    tx = parser._parse_sms_text(AIRTIME)
    assert tx['type'] == 'airtime'
    assert tx['recipient'] == 'Airtime'
    assert tx['merchant_category'] == 'utilities'


def test_withdrawal_at_agent(parser):
    tx = parser._parse_sms_text(WITHDRAW)
    assert tx['type'] == 'withdrawal'
    assert tx['amount'] == 1250.0
    assert tx['transaction_cost'] == 29.0
    assert tx['merchant_category'] == 'banking'
    assert tx['recipient'] == 'Edson Conveyors Goshen Accra Rd'


def test_give_cash_is_a_deposit_not_a_withdrawal(parser):
    tx = parser._parse_sms_text(DEPOSIT)
    assert tx['type'] == 'credit'
    assert tx['balance'] == 101.50
    assert tx['merchant_category'] == 'banking'


def test_reversal_credited_is_credit(parser):
    tx = parser._parse_sms_text(REVERSAL_CREDIT)
    assert tx['type'] == 'credit'
    assert tx['amount'] == 30.0
    assert tx['recipient'] == 'M-Pesa Reversal'
    assert tx['transaction_id'] == 'AB12CD34EO'


def test_reversal_debited_is_not_credit(parser):
    tx = parser._parse_sms_text(REVERSAL_DEBIT)
    assert tx['type'] == 'debit'
    assert tx['amount'] == 60.0


def test_card_payment_category_uses_account_text(parser):
    tx = parser._parse_sms_text(CARD)
    assert tx['merchant_category'] == 'entertainment'


@pytest.mark.parametrize('body', NON_TRANSACTIONS)
def test_non_transactions_are_rejected(parser, body):
    assert parser._parse_sms_text(body) is None


def test_footer_marketing_text_does_not_change_category(parser):
    body = (
        "AB12CD34EV Confirmed. Ksh50.00 paid to JOHN KAMAU. on 5/10/24 at 5:53 PM."
        "New M-PESA balance is Ksh100.00. Transaction cost, Ksh0.00. Sign up for Lipa Na M-PESA Till online. Buy goods with M-PESA."
    )
    assert parser._parse_sms_text(body)['merchant_category'] == 'other'


def test_substring_keywords_do_not_leak(parser):
    assert parser._categorize('', 'Barnabas Kimani') == 'other'
    assert parser._categorize('', 'Business Centre Bustani') == 'other'
    assert parser._categorize('', 'Uber Kenya') == 'transport'
    assert parser._categorize('', 'Java House Westgate') == 'food'


def test_amount_with_space_and_trailing_period(parser):
    assert parser._extract_amount("Ksh 59.53 from your M-PESA.") == 59.53
    assert parser._extract_amount("paid Ksh20. today") == 20.0
    assert parser._extract_amount("no money here") is None


def test_manual_sms_uses_date_inside_message(parser):
    tx = parser._parse_sms_text(SENT_P2P)
    assert tx['timestamp'].startswith('2024-10-03T12:40')


def test_manual_sms_accepts_pin_style_prefix(parser):
    tx = parser._parse_sms_text('1234-' + SENT_P2P)
    assert tx['transaction_id'] == 'AB12CD34EF'


def test_future_date_in_message_falls_back_to_now(parser):
    body = SENT_P2P.replace('3/10/24', '3/10/45')
    tx = parser._parse_sms_text(body)
    assert tx['timestamp'][:4] != '2045'


def test_timestamp_is_nairobi_not_utc(parser):
    ts = parser._parse_timestamp('1727948419665', '', SENT_P2P)
    assert (ts.hour, ts.minute) == (12, 40)


def test_timestamp_prefers_message_time_when_delivery_was_delayed(parser):
    body = "X Confirmed. on 23/4/26 at 8:00 AM Ksh10"
    ts = parser._parse_timestamp('1776932535771', '', body)
    assert (ts.hour, ts.minute) == (8, 0)


def test_phone_extraction_variants(parser):
    assert parser._extract_phone('to X 0712345678 on') == '0712345678'
    assert parser._extract_phone('to X 0112345678 on') == '0112345678'
    assert parser._extract_phone('to X 254712345678 on') == '254712345678'
    assert parser._extract_phone('from X 0707***979 on') == '0707***979'
    assert parser._extract_phone('account 104308 on') is None


def test_transaction_id_requires_a_digit(parser):
    assert parser._extract_transaction_id('CONFIRMEDXX something') is None
    assert parser._extract_transaction_id('AB12CD34EF Confirmed') == 'AB12CD34EF'


def test_xml_import_keeps_only_inbound_mpesa_sender(tmp_path, parser):
    xml = tmp_path / 'sms.xml'
    xml.write_text(
        '<?xml version="1.0"?><smses count="4">'
        f'<sms address="MPESA" type="1" date="1727948419665" body="{SENT_P2P}" readable_date="3 Oct 2024 12:40:19"/>'
        f'<sms address="MPESA" type="2" date="1727948419665" body="{SENT_PAYBILL}" readable_date="x"/>'
        f'<sms address="NCBA_BANK" type="1" date="1727948419665" body="{PAID_TILL}" readable_date="x"/>'
        f'<sms address="MPESA" type="1" date="1727948419665" body="{SENT_P2P}" readable_date="dup"/>'
        '</smses>',
        encoding='utf-8',
    )
    df = parser.parse_xml_to_csv(str(xml))
    assert list(df['transaction_id']) == ['AB12CD34EF']


def test_real_export_invariants(real_transactions):
    df = real_transactions
    assert len(df) > 0
    assert df['transaction_id'].is_unique
    assert (df['amount'] > 0).all()
    assert df['type'].isin(['credit', 'payment', 'withdrawal', 'airtime', 'debit', 'transfer']).all()
    assert df['merchant_category'].isin(MpesaParser.CATEGORIES).all()
    assert (df['recipient'] != 'Unknown').all()
    assert df['balance'].notna().all()
    assert not df['body'].str.contains('Fuliza M-PESA amount is', case=False).any()
    assert not df['body'].str.contains('account balance was', case=False).any()
    assert not df['body'].str.contains('Give Ksh', case=False).where(df['type'] != 'credit', False).any()


def test_real_export_balance_chain_is_consistent(real_transactions, parser):
    df = real_transactions.copy()
    df['message_time'] = df['body'].apply(parser._body_datetime)
    df = df.dropna(subset=['message_time']).sort_values(['message_time', 'raw_date']).reset_index(drop=True)
    checked = broken = 0
    for i in range(1, len(df)):
        prev, cur = df.loc[i - 1], df.loc[i]
        expected = prev['balance'] + cur['amount'] if cur['type'] == 'credit' else prev['balance'] - cur['amount'] - cur['transaction_cost']
        checked += 1
        if abs(expected - cur['balance']) > 0.011:
            broken += 1
    assert checked > 0
    assert broken / checked < 0.03
