import xml.etree.ElementTree as ET
import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Optional

class MpesaParser:
    def __init__(self):
        self.transactions = []
        
    def parse_xml_to_csv(self, xml_path: str) -> pd.DataFrame:
        """Parse M-Pesa SMS XML backup into CSV format"""
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        for sms in root.findall('.//sms'):
            body = sms.get('body', '')
            if 'M-PESA' in body:
                transaction = self._parse_sms(body)
                if transaction:
                    self.transactions.append(transaction)
        
        df = pd.DataFrame(self.transactions)
        df.to_csv('data/processed/mpesa_transactions.csv', index=False)
        return df
    
    def _parse_sms(self, body: str) -> Optional[Dict]:
        """Parse individual SMS body"""
        try:
            # Extract amount
            amount = self._extract_amount(body)
            if not amount:
                return None
                
            # Determine transaction type
            tx_type = self._determine_type(body)
            
            # Extract balance
            balance = self._extract_balance(body)
            
            # Extract recipient/merchant
            recipient = self._extract_recipient(body)
            
            # Extract date
            date = self._extract_date(body)
            
            # Determine merchant category
            category = self._categorize_merchant(body)
            
            return {
                'amount': amount,
                'balance': balance,
                'type': tx_type,
                'recipient': recipient,
                'merchant_category': category,
                'body': body,
                'timestamp': date,
                'transaction_id': self._generate_id(body)
            }
        except Exception as e:
            print(f"Error parsing SMS: {e}")
            return None
    
    def _extract_amount(self, body: str) -> Optional[float]:
        """Extract amount from SMS body"""
        patterns = [
            r'Ksh([\d,]+\.\d{2})',
            r'Ksh([\d,]+)',
            r'KES([\d,]+\.\d{2})',
            r'KES([\d,]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                amount = match.group(1).replace(',', '')
                return float(amount)
        return None
    
    def _determine_type(self, body: str) -> str:
        """Determine transaction type"""
        if 'received' in body.lower() or 'credited' in body.lower():
            return 'credit'
        elif 'paid to' in body.lower() or 'sent to' in body.lower():
            return 'payment'
        elif 'withdrawn' in body.lower():
            return 'withdrawal'
        elif 'airtime' in body.lower():
            return 'airtime'
        return 'debit'
    
    def _extract_balance(self, body: str) -> Optional[float]:
        """Extract account balance"""
        pattern = r'Balance:? Ksh([\d,]+\.\d{2})'
        match = re.search(pattern, body)
        if match:
            return float(match.group(1).replace(',', ''))
        return None
    
    def _extract_recipient(self, body: str) -> str:
        """Extract recipient name"""
        patterns = [
            r'paid to (.*?)(?:\s|$)',
            r'sent to (.*?)(?:\s|$)',
            r'received from (.*?)(?:\s|$)'
        ]
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                return match.group(1).strip()
        return 'Unknown'
    
    def _extract_date(self, body: str) -> Optional[datetime]:
        """Extract transaction date"""
        # Try multiple date formats
        patterns = [
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})'
        ]
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                try:
                    return datetime.strptime(match.group(1), '%d/%m/%y')
                except:
                    pass
        return datetime.now()
    
    def _categorize_merchant(self, body: str) -> str:
        """Categorize merchant based on keywords"""
        categories = {
            'food': ['restaurant', 'cafe', 'food', 'kfc', 'mcdonalds'],
            'shopping': ['supermarket', 'shop', 'store', 'mall'],
            'transport': ['uber', 'taxi', 'bus', 'train', 'fuel'],
            'bills': ['electricity', 'water', 'internet', 'bill'],
            'entertainment': ['cinema', 'movie', 'netflix', 'spotify']
        }
        
        body_lower = body.lower()
        for category, keywords in categories.items():
            if any(keyword in body_lower for keyword in keywords):
                return category
        return 'other'
    
    def _generate_id(self, body: str) -> str:
        """Generate unique transaction ID"""
        # Try to extract from SMS first
        match = re.search(r'ID:? (\w+)', body)
        if match:
            return match.group(1)
        # Generate hash if not present
        import hashlib
        return hashlib.md5(body.encode()).hexdigest()[:12]