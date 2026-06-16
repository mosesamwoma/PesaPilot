import xml.etree.ElementTree as ET
import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)

class MpesaParser:
    def __init__(self):
        self.transactions = []
        
    def parse_xml_to_csv(self, xml_path: str) -> pd.DataFrame:
        """Parse M-PESA SMS XML backup into CSV format"""
        logger.info(f"📂 Parsing XML file: {xml_path}")
        
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            logger.error(f"Failed to parse XML: {e}")
            return pd.DataFrame()
        
        # Find all SMS elements
        sms_elements = root.findall('.//sms')
        logger.info(f"📱 Found {len(sms_elements)} total SMS messages")
        
        mpesa_count = 0
        for sms in sms_elements:
            body = sms.get('body', '')
            # Check if it's an M-PESA message
            if self._is_mpesa_message(body):
                transaction = self._parse_sms(sms)
                if transaction:
                    self.transactions.append(transaction)
                    mpesa_count += 1
        
        logger.info(f"✅ Found {mpesa_count} M-PESA transactions")
        
        if self.transactions:
            df = pd.DataFrame(self.transactions)
            # Save to CSV
            import os
            os.makedirs('data/processed', exist_ok=True)
            df.to_csv('data/processed/mpesa_transactions.csv', index=False)
            logger.info(f"💾 Saved {len(df)} transactions to CSV")
            return df
        else:
            logger.warning("⚠️ No transactions found!")
            return pd.DataFrame()
    
    def _parse_sms(self, sms_element) -> Optional[Dict]:
        """Parse individual SMS element"""
        try:
            body = sms_element.get('body', '')
            if not body or not self._is_mpesa_message(body):
                return None
            
            # Extract transaction ID
            tx_id = self._extract_transaction_id(body)
            
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
            date = self._extract_date(sms_element)
            
            # Determine merchant category
            category = self._categorize_merchant(body)
            
            # Extract phone number
            phone = self._extract_phone(body)
            
            return {
                'transaction_id': tx_id,
                'amount': amount,
                'balance': balance,
                'type': tx_type,
                'recipient': recipient,
                'merchant_category': category,
                'phone': phone,
                'body': body[:500],  # Truncate for storage
                'timestamp': date,
                'readable_date': sms_element.get('readable_date', ''),
                'raw_date': sms_element.get('date', ''),
                'address': sms_element.get('address', '')
            }
        except Exception as e:
            logger.error(f"Error parsing SMS: {e}")
            return None
    
    def _is_mpesa_message(self, body: str) -> bool:
        """Check if message is M-PESA related"""
        keywords = ['M-PESA', 'Mpesa', 'MPESA', 'Confirmed', 'received', 'paid', 'balance']
        return any(keyword in body for keyword in keywords)
    
    def _extract_transaction_id(self, body: str) -> str:
        """Extract transaction ID from SMS body"""
        # Pattern for IDs like: SJ35QJGVLH, SJ39SL6JFF, etc.
        patterns = [
            r'^([A-Z0-9]{8,12})',  # Starts with transaction ID
            r'ID:?\s*([A-Z0-9]+)',
            r'Ref:?\s*([A-Z0-9]+)',
            r'Transaction ID:?\s*([A-Z0-9]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Fallback: generate hash
        return hashlib.md5(body.encode()).hexdigest()[:12]
    
    def _extract_amount(self, body: str) -> Optional[float]:
        """Extract amount from SMS body"""
        patterns = [
            r'Ksh([\d,]+\.\d{2})',
            r'Ksh([\d,]+)',
            r'KES([\d,]+\.\d{2})',
            r'KES([\d,]+)',
            r'KSh([\d,]+\.\d{2})',
            r'KSh([\d,]+)'
        ]
        
        # First try to find amount after context words
        context_patterns = [
            r'(?:paid|received|sent|withdraw|pay|credit)\s*(?:Ksh|KES|KSh)\s*([\d,]+\.\d{2})',
            r'(?:paid|received|sent|withdraw|pay|credit)\s*(?:Ksh|KES|KSh)\s*([\d,]+)'
        ]
        
        for pattern in context_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    return float(amount_str)
                except:
                    pass
        
        # Fallback: general amount patterns
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    return float(amount_str)
                except:
                    pass
        
        return None
    
    def _determine_type(self, body: str) -> str:
        """Determine transaction type"""
        body_lower = body.lower()
        
        if 'received' in body_lower or 'credited' in body_lower:
            if 'airtel money' in body_lower:
                return 'airtel_money'
            return 'credit'
        elif 'paid to' in body_lower or 'sent to' in body_lower:
            if 'airtime' in body_lower:
                return 'airtime'
            return 'payment'
        elif 'withdrawn' in body_lower:
            return 'withdrawal'
        elif 'airtime' in body_lower:
            return 'airtime'
        elif 'cancelled' in body_lower:
            return 'cancelled'
        elif 'failed' in body_lower:
            return 'failed'
        elif 'balance' in body_lower and 'transaction cost' not in body_lower:
            return 'balance_check'
        return 'debit'
    
    def _extract_balance(self, body: str) -> Optional[float]:
        """Extract account balance"""
        patterns = [
            r'balance is Ksh([\d,]+\.\d{2})',
            r'balance is Ksh([\d,]+)',
            r'New M-PESA balance is Ksh([\d,]+\.\d{2})',
            r'New M-PESA balance is Ksh([\d,]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                balance_str = match.group(1).replace(',', '')
                try:
                    return float(balance_str)
                except:
                    pass
        return None
    
    def _extract_recipient(self, body: str) -> str:
        """Extract recipient name"""
        patterns = [
            r'paid to ([A-Z\s\.]+?)(?:\.| on | at |\n|$)',
            r'sent to ([A-Z\s\.]+?)(?:\.| on | at |\n|$)',
            r'received from ([A-Z\s\.]+?)(?:\.| on | at |\n|$)',
            r'paid to ([A-Z\s\.]+?)(?:\s+on|\s+at|\s+for|\s*$)',
            r'sent to ([A-Z\s\.]+?)(?:\s+on|\s+at|\s+for|\s*$)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                recipient = match.group(1).strip()
                recipient = re.sub(r'\s+', ' ', recipient)
                if recipient and len(recipient) > 1:
                    return recipient
        
        # Try to extract from sender info
        match = re.search(r'from ([A-Z\s\.]+?)(?:\s+\d{10,12}| on | at |\n|$)', body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Check for merchant names
        match = re.search(r'to ([A-Z\s\.]+?)(?:\.| on | at |\n|$)', body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        return 'Unknown'
    
    def _extract_date(self, sms_element) -> datetime:
        """Extract date from SMS element"""
        # Try readable_date first
        readable = sms_element.get('readable_date', '')
        if readable:
            try:
                return datetime.strptime(readable, '%d %b %Y %H:%M:%S')
            except:
                pass
        
        # Try date attribute (milliseconds timestamp)
        date_str = sms_element.get('date', '')
        if date_str and date_str.isdigit():
            try:
                timestamp_ms = int(date_str)
                return datetime.fromtimestamp(timestamp_ms / 1000)
            except:
                pass
        
        # Try parsing from body
        body = sms_element.get('body', '')
        date_patterns = [
            r'on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
            r'on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{2,4})',
            r'(\d{1,2}/\d{1,2}/\d{2,4})'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, body)
            if match:
                try:
                    return datetime.strptime(match.group(1), '%d/%m/%y')
                except:
                    try:
                        return datetime.strptime(match.group(1), '%d %b %Y')
                    except:
                        pass
        
        return datetime.now()
    
    def _extract_phone(self, body: str) -> Optional[str]:
        """Extract phone number from SMS"""
        pattern = r'(?:\+?254|0)(?:[7-9]\d{8}|\d{9})'
        match = re.search(pattern, body)
        if match:
            return match.group(0)
        return None
    
    def _categorize_merchant(self, body: str) -> str:
        """Categorize merchant based on keywords"""
        categories = {
            'food': ['restaurant', 'cafe', 'food', 'kfc', 'mcdonalds', 'supermarket', 'shop', 'grocery'],
            'transport': ['uber', 'taxi', 'bus', 'train', 'fuel', 'uber'],
            'bills': ['electricity', 'water', 'internet', 'bill', 'kplc', 'token'],
            'entertainment': ['cinema', 'movie', 'netflix', 'spotify', 'google', 'apple', 'playstore'],
            'mobile': ['airtime', 'data', 'bundle', 'safaricom', 'airtel'],
            'banking': ['bank', 'loan', 'interest', 'equity', 'kcb', 'co-operative', 'ncba'],
            'shopping': ['store', 'shop', 'mall', 'market', 'grocery', 'wholesale'],
            'withdrawal': ['withdraw', 'agent', 'cash'],
            'salary': ['salary', 'payroll', 'equity bulk'],
            'investment': ['sacco', 'investment', 'shares', 'fuliza', 'ziidi']
        }
        
        body_lower = body.lower()
        
        # Specific merchant detection from your data
        if 'adan bacho' in body_lower:
            return 'payment'
        if 'isech international' in body_lower or 'is ech international' in body_lower:
            return 'entertainment'
        if 'vision wholesale' in body_lower:
            return 'shopping'
        if 'nathan salon' in body_lower:
            return 'personal_care'
        if 'till number' in body_lower or 'paybill' in body_lower:
            return 'bill_payment'
        if 'fuliza' in body_lower:
            return 'loan'
        if 'equity bulk' in body_lower:
            return 'salary'
        if 'airtel money' in body_lower:
            return 'mobile_money'
        
        for category, keywords in categories.items():
            if any(keyword in body_lower for keyword in keywords):
                return category
        
        return 'other'