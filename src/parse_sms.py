# src/parse_sms.py
import re
import pandas as pd
from lxml import etree
from datetime import datetime
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
        'business': ['till', 'lipa na mpesa', 'paybill', 'buy goods'],
    }

    def parse_xml_to_csv(self, xml_path: str, output_path: str = None) -> pd.DataFrame:
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

    def _parse_sms(self, elem) -> dict:
        body = elem.get('body', '')
        raw_date = elem.get('date', '')
        readable_date = elem.get('readable_date', '')
        address = elem.get('address', '')

        try:
            amount = self._extract_amount(body)
            if amount is None:
                return None

            tx_type = self._determine_type(body)
            recipient = self._extract_recipient(body)
            balance = self._extract_balance(body)
            tx_id = self._extract_transaction_id(body)
            phone = self._extract_phone(body) or address
            category = self._categorize(body, recipient)
            timestamp = self._parse_timestamp(raw_date, readable_date)

            return {
                'transaction_id': tx_id,
                'amount': amount,
                'balance': balance,
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

    def _extract_amount(self, body: str):
        patterns = [
            r'Ksh\s?([\d,]+\.?\d*)',
            r'KSh\s?([\d,]+\.?\d*)',
            r'KES\s?([\d,]+\.?\d*)',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                return float(m.group(1).replace(',', ''))
        return None

    def _extract_balance(self, body: str):
        patterns = [
            r'balance[:\s]+(?:is\s+)?Ksh\s?([\d,]+\.?\d*)',
            r'new\s+balance[:\s]+Ksh\s?([\d,]+\.?\d*)',
            r'balance\s+is\s+Ksh\s?([\d,]+\.?\d*)',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                return float(m.group(1).replace(',', ''))
        return None

    def _determine_type(self, body: str) -> str:
        body_lower = body.lower()
        if any(k in body_lower for k in ['you have received', 'received ksh', 'money in']):
            return 'credit'
        if any(k in body_lower for k in ['paid to', 'pay bill', 'paybill', 'buy goods', 'sent to', 'lipa na mpesa']):
            return 'payment'
        if any(k in body_lower for k in ['withdrew', 'withdrawal', 'cash out']):
            return 'withdrawal'
        if any(k in body_lower for k in ['airtime', 'data bundle', 'bundle']):
            return 'airtime'
        if any(k in body_lower for k in ['transferred', 'sent ksh', 'transfer']):
            return 'transfer'
        return 'debit'

    def _extract_recipient(self, body: str) -> str:
        patterns = [
            r'(?:paid to|sent to|pay to)\s+([A-Z][A-Z\s]+?)(?:\s+for|\s+on|\s+Ksh|\.|$)',
            r'to\s+([A-Z][A-Z\s]+?)\s+(?:account|for|on)',
            r'(?:to|for)\s+([A-Z][A-Z\s]{2,30})',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                return m.group(1).strip().title()
        return 'Unknown'

    def _extract_phone(self, body: str) -> str:
        m = re.search(r'(07\d{8}|2547\d{8}|\+2547\d{8})', body)
        return m.group(1) if m else None

    def _extract_transaction_id(self, body: str) -> str:
        m = re.search(r'\b([A-Z0-9]{10})\b', body)
        return m.group(1) if m else None

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