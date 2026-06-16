import os
from groq import Groq
import json
from typing import Dict, Any, List

class GroqClient:
    def __init__(self):
        self.api_key = os.environ.get('GROQ_API_KEY')
        if not self.api_key:
            raise ValueError("Missing GROQ_API_KEY")
        
        self.client = Groq(api_key=self.api_key)
        self.model = os.environ.get('LLM_MODEL', 'llama3-70b-8192')
        self.temperature = float(os.environ.get('LLM_TEMPERATURE', 0.7))
        self.max_tokens = int(os.environ.get('LLM_MAX_TOKENS', 1000))
    
    def generate_sql(self, question: str, schema: str) -> str:
        """Generate SQL query from natural language"""
        prompt = f"""
        You are an expert SQL generator for M-Pesa transaction data.
        
        Database schema:
        {schema}
        
        User question: {question}
        
        Generate a PostgreSQL query that answers this question.
        Return only the SQL query, no explanations.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a SQL expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Lower temperature for consistent SQL
            max_tokens=500
        )
        
        return response.choices[0].message.content
    
    def analyze_results(self, question: str, sql: str, results: List[Dict]) -> str:
        """Analyze query results and provide insights"""
        prompt = f"""
        You are a financial analyst reviewing M-Pesa transaction data.
        
        User question: {question}
        
        SQL query used:
        {sql}
        
        Results from database:
        {json.dumps(results[:10], indent=2)}
        Total rows: {len(results)}
        
        Provide a clear, concise analysis of these results.
        Include key insights and actionable recommendations.
        Keep it conversational but professional.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a financial analyst."},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        
        return response.choices[0].message.content
    
    def generate_insights(self, data: Dict) -> str:
        """Generate proactive financial insights"""
        prompt = f"""
        Analyze this M-Pesa transaction summary and provide financial insights.
        
        Data:
        {json.dumps(data, indent=2)}
        
        Provide:
        1. Spending patterns
        2. Potential savings opportunities
        3. Warnings about unusual spending
        4. Recommendations for better money management
        
        Be specific and actionable.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a financial advisor."},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        
        return response.choices[0].message.content
    
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