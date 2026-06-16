import os
from supabase import create_client, Client
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SupabaseDB:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL')
        self.key = os.environ.get('SUPABASE_KEY')
        if not self.url or not self.key:
            raise ValueError("Missing Supabase credentials. Please check .env file")
        
        self.client: Client = create_client(self.url, self.key)
        logger.info("✅ Supabase client initialized")
        
    def insert_transactions(self, transactions: List[Dict]) -> int:
        """Insert multiple transactions in batches"""
        if not transactions:
            return 0
            
        batch_size = int(os.environ.get('BATCH_SIZE', 100))
        inserted = 0
        
        for i in range(0, len(transactions), batch_size):
            batch = transactions[i:i+batch_size]
            try:
                result = self.client.table('transactions').insert(batch).execute()
                inserted += len(result.data)
                logger.info(f"✅ Inserted {len(result.data)} transactions")
            except Exception as e:
                logger.error(f"❌ Batch insert failed: {e}")
                # Try individual inserts for failed batch
                for tx in batch:
                    try:
                        self.client.table('transactions').insert(tx).execute()
                        inserted += 1
                    except Exception as e2:
                        logger.error(f"❌ Failed to insert transaction: {e2}")
        
        return inserted
    
    def get_transactions(self, days: int = 30, limit: int = 1000) -> pd.DataFrame:
        """Get recent transactions"""
        cutoff = datetime.now() - timedelta(days=days)
        try:
            response = self.client.table('transactions')\
                .select('*')\
                .gte('timestamp', cutoff.isoformat())\
                .order('timestamp', desc=True)\
                .limit(limit)\
                .execute()
            return pd.DataFrame(response.data)
        except Exception as e:
            logger.error(f"❌ Failed to get transactions: {e}")
            return pd.DataFrame()
    
    def get_summary(self) -> Dict:
        """Get transaction summary"""
        try:
            # Get daily summary
            daily = self.client.table('daily_summary')\
                .select('*')\
                .limit(30)\
                .execute()
            
            # Get category summary
            categories = self.client.table('category_summary')\
                .select('*')\
                .execute()
            
            # Get total counts
            total = self.client.table('transactions')\
                .select('count', count='exact')\
                .execute()
            
            return {
                'daily': pd.DataFrame(daily.data),
                'categories': pd.DataFrame(categories.data),
                'total_transactions': total.count if hasattr(total, 'count') else 0
            }
        except Exception as e:
            logger.error(f"❌ Failed to get summary: {e}")
            return {'daily': pd.DataFrame(), 'categories': pd.DataFrame(), 'total_transactions': 0}
    
    def execute_query(self, query: str) -> pd.DataFrame:
        """Execute raw SQL query"""
        try:
            # For Supabase, we need to use rpc or execute raw SQL
            # This assumes you've created the execute_sql function in Supabase
            response = self.client.rpc('execute_sql', {'query': query}).execute()
            return pd.DataFrame(response.data)
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            return pd.DataFrame()
    
    def detect_anomalies(self, threshold: float = 3.0, days_back: int = 90) -> pd.DataFrame:
        """Detect anomalous transactions"""
        try:
            response = self.client.rpc('detect_anomalies', {
                'threshold': threshold,
                'days_back': days_back
            }).execute()
            return pd.DataFrame(response.data)
        except Exception as e:
            logger.error(f"❌ Anomaly detection failed: {e}")
            return pd.DataFrame()
    
    def get_spending_trends(self, period: str = 'week', days: int = 90) -> pd.DataFrame:
        """Get spending trends by period"""
        try:
            # Get transactions and aggregate locally
            df = self.get_transactions(days=days)
            if df.empty:
                return pd.DataFrame()
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Group by period
            df['period'] = df['timestamp'].dt.to_period(period)
            
            trends = df.groupby('period').agg({
                'amount': lambda x: x[df['type'] == 'debit'].sum(),
                'transaction_id': 'count'
            }).reset_index()
            
            trends.columns = ['period', 'spending', 'transactions']
            trends['period'] = trends['period'].astype(str)
            
            return trends
        except Exception as e:
            logger.error(f"❌ Failed to get spending trends: {e}")
            return pd.DataFrame()