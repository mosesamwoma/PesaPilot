from src.database import SupabaseDB
from src.groq_client import GroqClient
from typing import Dict, Any
import pandas as pd
import json
import logging

logger = logging.getLogger(__name__)

class MpesaAnalyzer:
    def __init__(self):
        self.db = SupabaseDB()
        self.groq = GroqClient()
        self._schema = self._get_schema()
    
    def _get_schema(self) -> str:
        """Get database schema description"""
        return """
        Table: transactions
        - id: integer (primary key)
        - transaction_id: text (unique)
        - amount: decimal (10,2)
        - balance: decimal (10,2)
        - type: text (credit, debit, payment, withdrawal, airtime)
        - recipient: text
        - merchant_category: text (food, shopping, transport, bills, entertainment, other)
        - phone: text
        - body: text (full SMS)
        - timestamp: timestamp
        - readable_date: text
        - raw_date: text
        - created_at: timestamp
        
        Views:
        - daily_summary: date, total_transactions, total_spent, total_received, avg_spend, debit_count, credit_count
        - category_summary: merchant_category, transaction_count, total_amount, avg_amount, total_spent, total_received
        """
    
    def ask_question(self, question: str) -> Dict[str, Any]:
        """Process a natural language question"""
        try:
            # Generate SQL
            sql = self.groq.generate_sql(question, self._schema)
            logger.info(f"Generated SQL: {sql}")
            
            # Execute query
            results = self.db.execute_query(sql)
            
            # Analyze results
            analysis = self.groq.analyze_results(
                question, 
                sql, 
                results.to_dict('records') if not results.empty else []
            )
            
            return {
                'question': question,
                'sql': sql,
                'results': results.to_dict('records') if not results.empty else [],
                'analysis': analysis,
                'success': True
            }
        except Exception as e:
            logger.error(f"Error processing question: {e}")
            return {
                'question': question,
                'error': str(e),
                'success': False
            }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all data needed for dashboard"""
        try:
            summary = self.db.get_summary()
            anomalies = self.db.detect_anomalies()
            trends = self.db.get_spending_trends()
            
            # Get insights from Groq
            insights = self.groq.generate_insights({
                'summary': summary,
                'anomalies': anomalies.to_dict('records') if not anomalies.empty else [],
                'trends': trends.to_dict('records') if not trends.empty else []
            })
            
            return {
                'summary': summary,
                'anomalies': anomalies.to_dict('records') if not anomalies.empty else [],
                'trends': trends.to_dict('records') if not trends.empty else [],
                'insights': insights,
                'success': True
            }
        except Exception as e:
            logger.error(f"Error getting dashboard data: {e}")
            return {'error': str(e), 'success': False}
    
    def cache_dashboard_data(self) -> None:
        """Cache dashboard data for performance"""
        data = self.get_dashboard_data()
        with open('data/processed/dashboard_cache.json', 'w') as f:
            json.dump(data, f)