import re
import pandas as pd
from lxml import etree
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class MpesaParser:
    MERCHANT_CATEGORIES = {
        'food': ['java', 'kfc', 'naivas', 'quickmart', 'carrefour', 'food', 'restaurant', 'cafe', 'pizza', 'burger', 'chicken', 'bakery', 'grocery'],
        'transport': ['uber', 'bolt', 'little', 'taxi', 'matatu', 'bus', 'fuel', 'petrol', 'shell', 'total', 'kenol', 'rubis'],
        'utilities': ['kplc', 'kenya power', 'water', 'safaricom', 'airtel', 'telkom', 'internet', 'dstv', 'gotv', 'zuku'],
        'banking': ['equity', 'kcb', 'cooperative', 'absa', 'ncba', 'dtb', 'stanbic', 'bank', 'atm', 'loan', 'fuliza', 'mshwari', 'kcb mpesa'],
        'shopping': ['jumia', 'kilimall', 'supermarket', 'mall', 'shop', 'store', 'market'],
        'health': ['pharmacy', 'hospital', 'clinic', 'chemist', 'doctor', 'medical', 'health'],
        'education': ['school', 'university', 'college', 'fees', 'unilink', 'smep'],
        'entertainment': ['cinema', 'netflix', 'spotify', 'showmax', 'game', 'bar', 'club'],
        'savings': ['sacco', 'chama', 'savings', 'investment', 'shares'],
        'business': ['till', 'lipa na mpesa', 'paybill', 'buy goods', 'pochi la biashara', 'pochi'],
    }

    _RECIPIENT_TRIGGERS = [
        r'paid to\s+',
        r'sent to\s+',
        r'pay to\s+',
        r'received\s+Ksh[\d,.]+\s+from\s+',
        r'\bfrom\s+',
        r'\bto\s+',
        r'\bfor\s+',
    ]
    _NAME_BOUNDARY_RE = re.compile(
        r'([A-Za-z][A-Za-z0-9\s\.\-\'\u2019\\]{0,88}?)'
        r'(?=\s+(?:on\b|for\b|New\s+M-?PESA\b)|\s+[\d\*]{3,}|[.,]|$)',
        re.IGNORECASE,
    )
    _AGENT_PREFIX_RE = re.compile(r'^[\d]+\s*-\s*')
    _NON_TRANSACTION_RE = re.compile(
        r'account balance was|'
        r'you have cancelled the transaction|'
        r'transaction failed|'
        r'cannot complete|'
        r'do not have enough money|'
        r'request (?:has\s+)?(?:been\s+)?cancelled|'
        r'invalid input',
        re.IGNORECASE,
    )

    def parse_xml_to_csv(self, xml_path: str, output_path: Optional[str] = None) -> pd.DataFrame:
        logger.info(f"Parsing XML: {xml_path}")
        transactions = []

        context = etree.iterparse(xml_path, events=('end',), tag='sms')
        for _, elem in context:
            body = elem.get('body', '')
            if not self._is_mpesa(body):
                elem.clear()
                continue
            tx = self._parse_sms(elem)
            if tx:
                transactions.append(tx)
            elem.clear()

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

    def _is_mpesa(self, body: str) -> bool:
        return bool(re.search(r'M-PESA|MPESA|Ksh|KSh', body, re.IGNORECASE))

    def _is_non_transaction(self, body: str) -> bool:
        return bool(self._NON_TRANSACTION_RE.search(body))

    def _parse_sms(self, elem) -> Optional[dict]:
        body = elem.get('body', '')
        raw_date = elem.get('date', '')
        readable_date = elem.get('readable_date', '')
        address = elem.get('address', '')

        try:
            if self._is_non_transaction(body):
                return None

            amount = self._extract_amount(body)
            if amount is None:
                return None

            tx_type = self._determine_type(body)
            recipient = self._extract_recipient(body)
            balance = self._extract_balance(body)
            transaction_cost = self._extract_transaction_cost(body)
            tx_id = self._extract_transaction_id(body)
            if tx_id is None:
                logger.debug(f"Skipping SMS with no transaction ID: {body[:60]!r}")
                return None
            phone = self._extract_phone(body) or address
            category = self._categorize(body, recipient)
            timestamp = self._parse_timestamp(raw_date, readable_date)

            return {
                'transaction_id': tx_id,
                'amount': amount,
                'balance': balance,
                'transaction_cost': transaction_cost,
                'type': tx_type,
                'recipient': recipient,
                'merchant_category': category,
                'phone': phone,
                'body': body,
                'timestamp': timestamp,
                'readable_date': readable_date,
                'raw_date': raw_date,
            }
        except Exception as e:
            logger.debug(f"Failed to parse SMS: {e}")
            return None

    def _parse_sms_text(self, body: str) -> Optional[dict]:
        try:
            if self._is_non_transaction(body):
                return None

            amount = self._extract_amount(body)
            if amount is None:
                return None

            tx_type = self._determine_type(body)
            recipient = self._extract_recipient(body)
            balance = self._extract_balance(body)
            transaction_cost = self._extract_transaction_cost(body)
            tx_id = self._extract_transaction_id(body)
            phone = self._extract_phone(body)
            category = self._categorize(body, recipient)
            timestamp = datetime.now()

            return {
                'transaction_id': tx_id or f"MANUAL_{int(datetime.now().timestamp())}",
                'amount': amount,
                'balance': balance,
                'transaction_cost': transaction_cost,
                'type': tx_type,
                'recipient': recipient,
                'merchant_category': category,
                'phone': phone,
                'body': body,
                'timestamp': timestamp.isoformat(),
                'readable_date': timestamp.strftime('%d/%m/%Y %H:%M:%S'),
                'raw_date': str(int(timestamp.timestamp() * 1000)),
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None

    def _extract_amount(self, body: str):
        patterns = [
            r'Ksh\s?([\d,]+\.?\d*)',
            r'KES\s?([\d,]+\.?\d*)',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                value = float(m.group(1).replace(',', ''))
                if value == 0.0:
                    for m2 in re.finditer(p, body, re.IGNORECASE):
                        v2 = float(m2.group(1).replace(',', ''))
                        if v2 > 0:
                            return v2
                    return value
                return value
        return None

    def _extract_transaction_cost(self, body: str) -> float:
        m = re.search(r'transaction\s*cost,?\s*Ksh\.?\s?([\d,]+\.?\d*)', body, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(',', ''))
            except ValueError:
                return 0.0
        return 0.0

    def _extract_balance(self, body: str):
        patterns = [
            r'(?:new\s+)?(?:m-?pesa\s+)?balance\s+is\s+Ksh\s?([\d,]+\.?\d*)',
            r'balance[:\s]+Ksh\s?([\d,]+\.?\d*)',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                return float(m.group(1).replace(',', ''))
        return None

    def _determine_type(self, body: str) -> str:
        body_lower = body.lower()
        if any(k in body_lower for k in ['withdraw', 'withdrew', 'cash out']) or re.search(r'give\s+ksh[\d,.]*\s*cash\s+to', body_lower):
            return 'withdrawal'
        if any(k in body_lower for k in ['you have received', 'received ksh', 'money in']) or 'is credited to your m-pesa' in body_lower:
            return 'credit'
        if any(k in body_lower for k in ['paid to', 'pay bill', 'paybill', 'buy goods', 'sent to', 'lipa na mpesa']):
            return 'payment'
        if any(k in body_lower for k in ['airtime', 'data bundle', 'bundle']):
            return 'airtime'
        if any(k in body_lower for k in ['transferred', 'sent ksh', 'transfer']):
            return 'transfer'
        return 'debit'

    def _extract_recipient(self, body: str) -> str:
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
                return name.title()
        return 'Unknown'

    def _extract_phone(self, body: str) -> Optional[str]:
        m = re.search(r'(07\d{8}|2547\d{8}|\+2547\d{8})', body)
        return m.group(1) if m else None

    def _extract_transaction_id(self, body: str) -> Optional[str]:
        for m in re.finditer(r'\b([A-Z][A-Z0-9]{9,})\b', body):
            tx_id = m.group(1)
            if tx_id.upper() == 'M-PESA':
                continue
            if not re.search(r'\d', tx_id):
                continue
            return tx_id
        return None

    def _categorize(self, body: str, recipient: str) -> str:
        text = (body + ' ' + (recipient or '')).lower()
        for category, keywords in self.MERCHANT_CATEGORIES.items():
            if any(k in text for k in keywords):
                return category
        return 'other'

    def _parse_timestamp(self, raw_date: str, readable_date: str):
        if raw_date and raw_date.isdigit():
            try:
                return datetime.fromtimestamp(int(raw_date) / 1000)
            except Exception:
                pass
        formats = ['%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%b %d, %Y %I:%M:%S %p']
        for fmt in formats:
            try:
                return datetime.strptime(readable_date, fmt)
            except Exception:
                continue
        return datetime.now()