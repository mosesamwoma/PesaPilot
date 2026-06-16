import os
from groq import Groq
import json
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class GroqClient:
    def __init__(self):
        self.api_key = os.environ.get('GROQ_API_KEY')
        if not self.api_key:
            raise ValueError("Missing GROQ_API_KEY. Please check .env file")
        
        self.client = Groq(api_key=self.api_key)
        self.model = os.environ.get('LLM_MODEL', 'llama3-70b-8192')
        self.temperature = float(os.environ.get('LLM_TEMPERATURE', 0.7))
        self.max_tokens = int(os.environ.get('LLM_MAX_TOKENS', 1000))
        logger.info(f"✅ Groq client initialized with model: {self.model}")
    
    def generate_sql(self, question: str, schema: str) -> str:
        """Generate SQL query from natural language"""
        prompt = f"""
        You are an expert SQL generator for M-PESA transaction data.
        
        Database schema:
        {schema}
        
        User question: {question}
        
        Important rules:
        1. Use PostgreSQL syntax
        2. Only use SELECT statements (no INSERT, UPDATE, DELETE)
        3. Use safe column names (no SQL injection)
        4. Limit results to 100 rows unless specified
        
        Generate a PostgreSQL query that answers this question.
        Return ONLY the SQL query, no explanations, no markdown.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a SQL expert. Return only SQL queries."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Lower temperature for consistent SQL
                max_tokens=500
            )
            
            sql = response.choices[0].message.content
            # Clean up the SQL
            sql = sql.replace('```sql', '').replace('```', '').strip()
            return sql
        except Exception as e:
            logger.error(f"❌ Groq SQL generation failed: {e}")
            return ""
    
    def analyze_results(self, question: str, sql: str, results: List[Dict], result_count: int = 0) -> str:
        """Analyze query results and provide insights"""
        # Truncate results for token limit
        result_sample = results[:10] if results else []
        total_count = result_count or len(results)
        
        prompt = f"""
        You are a financial analyst reviewing M-PESA transaction data.
        
        User question: {question}
        
        SQL query used:
        {sql}
        
        Results from database (showing first 10):
        {json.dumps(result_sample, indent=2, default=str)}
        Total rows: {total_count}
        
        Provide a clear, concise analysis of these results.
        Include:
        1. Key findings from the data
        2. Any patterns or trends you notice
        3. Actionable recommendations
        4. Keep it conversational but professional
        5. Use bullet points for clarity
        
        Format the response in markdown for readability.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a financial analyst. Provide clear, actionable insights."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ Groq analysis failed: {e}")
            return f"I encountered an error analyzing the results: {str(e)}"
    
    def generate_insights(self, data: Dict) -> str:
        """Generate proactive financial insights"""
        # Format data for the prompt
        summary = data.get('summary', {})
        anomalies = data.get('anomalies', [])
        trends = data.get('trends', [])
        
        prompt = f"""
        You are a financial advisor analyzing M-PESA transaction data.
        
        Summary Data:
        - Total transactions: {summary.get('total_transactions', 0)}
        - Daily spending trends: {json.dumps(trends[:10], indent=2, default=str) if trends else 'No data'}
        - Top spending categories: {json.dumps(summary.get('categories', [])[:5], indent=2, default=str)}
        - Anomalies detected: {len(anomalies)} unusual transactions
        
        Provide a comprehensive financial analysis including:
        1. Spending patterns and habits
        2. Potential savings opportunities
        3. Warnings about unusual spending
        4. Recommendations for better money management
        5. Budgeting advice based on the data
        
        Be specific, actionable, and data-driven.
        Format in markdown with clear sections.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a financial advisor. Provide practical, data-driven advice."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ Groq insights generation failed: {e}")
            return f"I encountered an error generating insights: {str(e)}"
    
    def format_response(self, text: str) -> str:
        """Format response for better readability"""
        # Clean up markdown
        text = text.replace('**', '')
        text = text.replace('*', '')
        
        # Format bullet points
        lines = text.split('\n')
        formatted = []
        for line in lines:
            if line.strip().startswith('-'):
                formatted.append(f"• {line.strip()[1:]}")
            else:
                formatted.append(line)
        
        return '\n'.join(formatted)