import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
from lxml import etree

from src.timeutil import from_epoch_ms, now_nairobi

logger = logging.getLogger(__name__)


class MpesaParser:
    MERCHANT_CATEGORIES = {
        'food': ['java', 'kfc', 'naivas', 'quickmart', 'carrefour', 'food', 'restaurant', 'cafe', 'pizza',
                 'burger', 'chicken', 'bakery', 'grocery', 'groceries', 'butchery', 'eatery'],
        'transport': ['uber', 'bolt', 'little', 'taxi', 'matatu', 'bus', 'fuel', 'petrol', 'shell', 'total',
                      'kenol', 'rubis', 'sgr'],
        'utilities': ['kplc', 'kenya power', 'water', 'safaricom', 'airtel', 'telkom', 'internet', 'dstv',
                      'gotv', 'zuku', 'wifi', 'wireless', 'networks', 'airtime', 'bundles', 'tunukiwa'],
        'banking': ['equity', 'kcb', 'cooperative', 'absa', 'ncba', 'dtb', 'stanbic', 'bank', 'atm', 'loan',
                    'fuliza', 'mshwari', 'm-shwari', 'im bank'],
        'shopping': ['jumia', 'kilimall', 'supermarket', 'mall', 'shop', 'store', 'market', 'wholesale',
                     'retail', 'boutique', 'hardware'],
        'health': ['pharmacy', 'hospital', 'clinic', 'chemist', 'doctor', 'medical', 'health'],
        'education': ['school', 'university', 'college', 'fees', 'unilink', 'smep', 'student', 'students',
                      'academy', 'helb'],
        'entertainment': ['cinema', 'netflix', 'spotify', 'showmax', 'game', 'bar', 'club', 'efootball',
                          'playstation', 'steam'],
        'savings': ['sacco', 'chama', 'savings', 'investment', 'shares', 'mmf', 'ziidi'],
        'business': ['till', 'lipa na mpesa', 'paybill', 'buy goods', 'pochi la biashara', 'pochi'],
    }

    CATEGORIES = tuple(MERCHANT_CATEGORIES) + ('personal', 'other')

    _SUBSTRING_KEYWORDS = frozenset({
        'java', 'kfc', 'naivas', 'quickmart', 'carrefour', 'kplc', 'safaricom', 'airtel', 'telkom', 'wifi',
        'jumia', 'kilimall', 'pharmacy', 'hospital', 'netflix', 'spotify', 'showmax', 'efootball', 'sacco',
        'equity', 'mshwari', 'fuliza', 'supermarket', 'wholesale', 'butchery', 'dstv', 'gotv', 'zuku',
        'playstation',
    })

    _RECIPIENT_TRIGGERS = [
        r'paid to\s+',
        r'sent to\s+',
        r'pay to\s+',
        r'received\s+Ksh\s?[\d,.]+\s+from\s+',
        r'Give\s+Ksh\s?[\d,.]+\s+cash\s+to\s+',
        r'Withdraw\s+Ksh\s?[\d,.]+\s+from\s+',
        r'\bfrom\s+',
        r'\bto\s+',
        r'\bfor\s+',
    ]
    _NAME_BOUNDARY_RE = re.compile(
        r'([A-Za-z][A-Za-z0-9\s\.\-\'\u2019\\&\(\)_]{0,88}?)'
        r'(?=\s+(?:on\b|for\b|New\s+M-?PESA\b)|\s+[\d\*]{3,}|[.,]\s|[.,]$|$)',
        re.IGNORECASE,
    )
    _AGENT_PREFIX_RE = re.compile(r'^[\d]+\s*-\s*')
    _PHONE_RE = re.compile(r'(?<![\d*])((?:\+?254|0)[17]\d{2}(?:\d{6}|\*{3}\d{3}))(?!\d)')
    _BODY_DATE_RE = re.compile(
        r'(\d{1,2})/(\d{1,2})/(\d{2,4})\s+at\s+(\d{1,2}):(\d{2})\s*([AP]M)', re.IGNORECASE,
    )
    _ACCOUNT_RE = re.compile(r'for account\s+(.+?)\s+on\s+\d{1,2}/\d{1,2}/\d{2,4}', re.IGNORECASE)
    _NON_TRANSACTION_RE = re.compile(
        r'account balance was|'
        r'you have cancelled the transaction|'
        r'transaction failed|'
        r'cannot complete|'
        r'do not have enough money|'
        r'do not have sufficient funds|'
        r'insufficient funds|'
        r'request (?:has\s+)?(?:been\s+)?cancelled|'
        r'invalid input|'
        r'unable to process|'
        r'has not joined the service|'
        r'declined reversal|'
        r'wrong pin|'
        r'^\s*failed\b|'
        r'fuliza m-?pesa amount is|'
        r'used to (?:fully|partially) pay your outstanding fuliza|'
        r'cannot receive airtime|'
        r'sim card has been activated',
        re.IGNORECASE | re.MULTILINE,
    )
    _TX_HEADER_RE = re.compile(r'^\W*([A-Z0-9]{10})\s+(?i:confirmed)\b')
    _MANUAL_PREFIX_RE = re.compile(r'^\s*\d{3,8}\s*-\s*')

    def parse_xml_to_csv(self, xml_path: str, output_path: Optional[str] = None) -> pd.DataFrame:
        logger.info(f"Parsing XML: {xml_path}")
        transactions = []

        context = etree.iterparse(xml_path, events=('end',), tag='sms', recover=True)
        for _, elem in context:
            try:
                if self._is_inbound_mpesa(elem):
                    tx = self._parse_sms(elem)
                    if tx:
                        transactions.append(tx)
            finally:
                elem.clear()
                while elem.getprevious() is not None:
                    parent = elem.getparent()
                    if parent is None:
                        break
                    del parent[0]

        df = pd.DataFrame(transactions)
        if df.empty:
            logger.warning("No M-Pesa transactions found.")
            return df

        df = df.drop_duplicates(subset=['transaction_id'], keep='first')
        df = df.sort_values('timestamp', ascending=False).reset_index(drop=True)

        if output_path:
            df.to_csv(output_path, index=False)
            logger.info(f"Saved {len(df)} transactions to {output_path}")

        return df

    def _is_inbound_mpesa(self, elem) -> bool:
        sender = re.sub(r'[^a-z]', '', (elem.get('address') or '').lower())
        if sender != 'mpesa':
            return False
        if (elem.get('type') or '1') != '1':
            return False
        return self._is_mpesa(elem.get('body') or '')

    def _is_mpesa(self, body: str) -> bool:
        return bool(re.search(r'M-PESA|MPESA|Ksh|KSh', body or '', re.IGNORECASE))

    def _is_non_transaction(self, body: str) -> bool:
        return bool(self._NON_TRANSACTION_RE.search(body))

    def _build_record(self, body: str) -> Optional[dict]:
        if self._is_non_transaction(body):
            return None

        amount = self._extract_amount(body)
        if amount is None:
            return None

        tx_id = self._extract_transaction_id(body)
        tx_type = self._determine_type(body)
        recipient = self._extract_recipient(body, tx_type)
        phone = self._extract_phone(body)
        category = self._categorize(body, recipient, tx_type=tx_type, phone=phone)

        return {
            'transaction_id': tx_id,
            'amount': amount,
            'balance': self._extract_balance(body),
            'transaction_cost': self._extract_transaction_cost(body),
            'type': tx_type,
            'recipient': recipient,
            'merchant_category': category,
            'phone': phone,
            'body': body,
        }

    def _parse_sms(self, elem) -> Optional[dict]:
        body = elem.get('body') or ''
        raw_date = elem.get('date') or ''
        readable_date = elem.get('readable_date') or ''

        try:
            record = self._build_record(body)
            if record is None:
                return None
            if record['transaction_id'] is None:
                logger.debug(f"Skipping SMS with no transaction ID: {body[:60]!r}")
                return None

            timestamp = self._parse_timestamp(raw_date, readable_date, body)
            record.update({
                'timestamp': timestamp,
                'readable_date': readable_date,
                'raw_date': raw_date,
            })
            return record
        except Exception as e:
            logger.debug(f"Failed to parse SMS: {e}")
            return None

    def _parse_sms_text(self, body: str) -> Optional[dict]:
        try:
            body = self._MANUAL_PREFIX_RE.sub('', body or '', count=1).strip()
            record = self._build_record(body)
            if record is None:
                return None

            now = now_nairobi()
            timestamp = self._body_datetime(body) or now
            if timestamp > now + timedelta(days=1):
                timestamp = now

            if record['transaction_id'] is None:
                return None

            record.update({
                'timestamp': timestamp.isoformat(),
                'readable_date': timestamp.strftime('%d/%m/%Y %H:%M:%S'),
                'raw_date': str(int(timestamp.timestamp() * 1000)),
            })
            return record
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None

    def _extract_amount(self, body: str) -> Optional[float]:
        values = []
        for m in re.finditer(r'(?:Ksh|KES)\.?\s?(\d[\d,]*(?:\.\d+)?)', body, re.IGNORECASE):
            try:
                values.append(float(m.group(1).replace(',', '')))
            except ValueError:
                continue
        if not values:
            return None
        if values[0] > 0:
            return values[0]
        for v in values[1:]:
            if v > 0:
                return v
        return values[0]

    def _extract_transaction_cost(self, body: str) -> float:
        m = re.search(r'transaction\s*(?:cost|fee),?\s*(?:Ksh|KES)\.?\s?(\d[\d,]*(?:\.\d+)?)', body, re.IGNORECASE)
        if not m:
            return 0.0
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            return 0.0

    def _extract_balance(self, body: str) -> Optional[float]:
        patterns = [
            r'balance\s+is\s+(?:Ksh|KES)\.?\s?(\d[\d,]*(?:\.\d+)?)',
            r'balance[:\s]+(?:Ksh|KES)\.?\s?(\d[\d,]*(?:\.\d+)?)',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except ValueError:
                    continue
        return None

    def _determine_type(self, body: str) -> str:
        lower = body.lower()
        if re.search(r'reversal of transaction', lower) and 'credited' in lower:
            return 'credit'
        if re.search(r'give\s+ksh\s?[\d,.]+\s*cash\s+to', lower):
            return 'credit'
        if re.search(r'withdraw\s+ksh|ksh\s?[\d,.]+\s+withdrawn|withdrew|cash out', lower):
            return 'withdrawal'
        if re.search(r'you have received|received ksh|money in', lower) or 'is credited to your m-pesa' in lower:
            return 'credit'
        if re.search(r'you bought ksh\s?[\d,.]+ of airtime', lower):
            return 'airtime'
        if re.search(r'paid to|pay bill|paybill|buy goods|sent to|lipa na mpesa', lower):
            return 'payment'
        if re.search(r'airtime|data bundle|bundle', lower):
            return 'airtime'
        if re.search(r'transferred|sent ksh|transfer', lower):
            return 'transfer'
        return 'debit'

    def _extract_recipient(self, body: str, tx_type: Optional[str] = None) -> str:
        lower = body.lower()
        if 'reversal of transaction' in lower:
            return 'M-Pesa Reversal'
        if tx_type == 'airtime' and re.search(r'you bought', lower):
            return 'Airtime'

        for trigger in self._RECIPIENT_TRIGGERS:
            m = re.search(trigger, body, re.IGNORECASE)
            if not m:
                continue
            tail = body[m.end():]
            tail = self._AGENT_PREFIX_RE.sub('', tail)
            name_match = self._NAME_BOUNDARY_RE.match(tail)
            if not name_match:
                continue
            name = name_match.group(1).replace('\\', '')
            name = re.sub(r'\s+', ' ', name).strip(' .-')
            if len(name) >= 2 and re.search(r'[A-Za-z]', name):
                if name.lower() == 'm-pesa card':
                    account = self._ACCOUNT_RE.search(body)
                    merchant = re.sub(r'\s+', ' ', re.sub(r'\bg\.co/\S+', '', account.group(1))).strip(' .-') if account else ''
                    if merchant:
                        return merchant.title()
                return name.title()
        return 'Unknown'

    def _extract_phone(self, body: str) -> Optional[str]:
        m = self._PHONE_RE.search(body)
        return m.group(1) if m else None

    def _extract_transaction_id(self, body: str) -> Optional[str]:
        m = self._TX_HEADER_RE.match(body or '')
        return m.group(1) if m else None

    def _keyword_matches(self, text: str, keyword: str) -> bool:
        if keyword in self._SUBSTRING_KEYWORDS:
            return keyword in text
        return re.search(rf'(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])', text) is not None

    def _categorize(self, body: str, recipient: str, tx_type: Optional[str] = None,
                    phone: Optional[str] = None) -> str:
        body_lower = (body or '').lower()
        if tx_type == 'withdrawal' or re.search(r'give\s+ksh\s?[\d,.]+\s*cash\s+to', body_lower):
            return 'banking'
        if 'reversal of transaction' in body_lower:
            return 'other'

        account_match = self._ACCOUNT_RE.search(body or '')
        account = account_match.group(1) if account_match else ''
        text = f"{recipient or ''} {account}".lower()

        if tx_type == 'credit':
            if 'airtel money' in text or phone:
                return 'personal'
            for category in ('banking', 'savings', 'education'):
                if any(self._keyword_matches(text, k) for k in self.MERCHANT_CATEGORIES[category]):
                    return category
            return 'other'

        for category, keywords in self.MERCHANT_CATEGORIES.items():
            if any(self._keyword_matches(text, k) for k in keywords):
                return category
        if tx_type == 'airtime':
            return 'utilities'
        if phone and tx_type in ('payment', 'transfer'):
            return 'personal'
        return 'other'

    def _body_datetime(self, body: str) -> Optional[datetime]:
        m = self._BODY_DATE_RE.search(body or '')
        if not m:
            return None
        day, month, year, hour, minute, meridiem = m.groups()
        year_i = int(year)
        if year_i < 100:
            year_i += 2000
        hour_i = int(hour) % 12 + (12 if meridiem.upper() == 'PM' else 0)
        try:
            return datetime(year_i, int(month), int(day), hour_i, int(minute))
        except ValueError:
            return None

    def _parse_timestamp(self, raw_date: str, readable_date: str, body: str = '') -> datetime:
        received = from_epoch_ms(raw_date) if raw_date and raw_date.isdigit() else None
        in_body = self._body_datetime(body)

        if received is not None:
            if in_body is not None and abs(received - in_body) > timedelta(minutes=10):
                return in_body
            return received
        if in_body is not None:
            return in_body

        formats = ['%d %b %Y %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S',
                   '%d-%m-%Y %H:%M:%S', '%b %d, %Y %I:%M:%S %p']
        for fmt in formats:
            try:
                return datetime.strptime(readable_date, fmt)
            except (TypeError, ValueError):
                continue
        return now_nairobi()

    def summarize(self, df: pd.DataFrame) -> Dict:
        if df is None or df.empty:
            return {'transactions': 0}
        return {
            'transactions': int(len(df)),
            'first': str(df['timestamp'].min()),
            'last': str(df['timestamp'].max()),
            'by_type': df['type'].value_counts().to_dict(),
        }
