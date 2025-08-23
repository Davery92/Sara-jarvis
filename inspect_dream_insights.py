#!/usr/bin/env python3
"""
Inspect dream insights in the Sara database to understand the data structure and find items with invalid dates
"""

import psycopg
from datetime import datetime
import json

def inspect_dream_insights():
    """Connect to PostgreSQL and inspect dream insights"""
    
    try:
        # Connect to PostgreSQL
        conn = psycopg.connect('postgresql://sara:sara123@10.185.1.180:5432/sara_hub')
        cur = conn.cursor()
        
        # Check if dream_insight table exists
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema='public' AND table_name = 'dream_insight';
        """)
        table_exists = cur.fetchone()
        
        if not table_exists:
            print("❌ dream_insight table does not exist in the database")
            return
            
        print("✅ dream_insight table found")
        
        # Get table schema
        print("\n📋 Table Schema:")
        cur.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'dream_insight'
            ORDER BY ordinal_position;
        """)
        columns = cur.fetchall()
        
        for col_name, data_type, is_nullable in columns:
            print(f"  {col_name}: {data_type} ({'nullable' if is_nullable == 'YES' else 'not null'})")
        
        # Count total dream insights
        cur.execute("SELECT COUNT(*) FROM dream_insight;")
        total_count = cur.fetchone()[0]
        print(f"\n📊 Total dream insights: {total_count}")
        
        if total_count == 0:
            print("ℹ️  No dream insights found in database")
            return
            
        # Group by insight type
        cur.execute("SELECT insight_type, COUNT(*) FROM dream_insight GROUP BY insight_type ORDER BY COUNT(*) DESC;")
        types = cur.fetchall()
        print("\n📈 Insights by type:")
        for insight_type, count in types:
            print(f"  {insight_type}: {count}")
            
        # Group by user
        cur.execute("SELECT user_id, COUNT(*) FROM dream_insight GROUP BY user_id ORDER BY COUNT(*) DESC;")
        users = cur.fetchall()
        print("\n👥 Insights by user:")
        for user_id, count in users:
            print(f"  {user_id}: {count}")
        
        # Check for date issues
        print("\n📅 Date Analysis:")
        cur.execute("SELECT MIN(dream_date), MAX(dream_date) FROM dream_insight;")
        date_range = cur.fetchone()
        if date_range[0] and date_range[1]:
            print(f"  Date range: {date_range[0]} to {date_range[1]}")
            
            # Check for future dates
            cur.execute("SELECT COUNT(*) FROM dream_insight WHERE dream_date > NOW();")
            future_count = cur.fetchone()[0]
            print(f"  Future dates: {future_count}")
            
            # Check for very old dates (before 2023)
            cur.execute("SELECT COUNT(*) FROM dream_insight WHERE dream_date < '2023-01-01';")
            old_count = cur.fetchone()[0]
            print(f"  Very old dates (before 2023): {old_count}")
        
        # Show some sample insights
        print("\n📖 Sample insights:")
        cur.execute("""
            SELECT id, dream_date, insight_type, title, confidence, 
                   LEFT(content, 100) as content_preview
            FROM dream_insight 
            ORDER BY dream_date DESC 
            LIMIT 5;
        """)
        samples = cur.fetchall()
        
        for insight in samples:
            id_val, dream_date, insight_type, title, confidence, content_preview = insight
            print(f"  {dream_date} | {insight_type} | {title} | {confidence:.2f}")
            print(f"    {content_preview}...")
            print()
        
        # Check for problematic dates in detail
        print("🔍 Checking for problematic dates:")
        cur.execute("""
            SELECT id, dream_date, insight_type, title 
            FROM dream_insight 
            WHERE dream_date > NOW() OR dream_date < '2023-01-01'
            ORDER BY dream_date;
        """)
        problematic = cur.fetchall()
        
        if problematic:
            print(f"Found {len(problematic)} insights with problematic dates:")
            for insight in problematic:
                id_val, dream_date, insight_type, title = insight
                print(f"  {id_val} | {dream_date} | {insight_type} | {title}")
        else:
            print("  No insights with problematic dates found")
        
    except Exception as e:
        print(f"❌ Error inspecting dream insights: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def check_neo4j_dream_data():
    """Check Neo4j for any dream-related data"""
    try:
        from neo4j import GraphDatabase
        
        # Neo4j connection
        uri = "bolt://10.185.1.180:7687"
        username = "neo4j"
        password = "sara-graph-secret"
        
        driver = GraphDatabase.driver(uri, auth=(username, password))
        
        with driver.session() as session:
            # Check for dream-related nodes
            result = session.run("""
                MATCH (n)
                WHERE toLower(n.title) CONTAINS 'dream' 
                   OR toLower(n.content) CONTAINS 'dream'
                   OR toLower(n.title) CONTAINS 'insight'
                   OR toLower(n.content) CONTAINS 'insight'
                RETURN labels(n) as labels, n.title as title, n.id as id, n.content_type as content_type
                LIMIT 10
            """)
            
            dream_nodes = list(result)
            print(f"\n🧠 Neo4j dream/insight related nodes: {len(dream_nodes)}")
            
            if dream_nodes:
                for record in dream_nodes:
                    labels = record["labels"]
                    title = record["title"]
                    node_id = record["id"]
                    content_type = record["content_type"]
                    print(f"  {labels} | {title} | {node_id} | {content_type}")
        
        driver.close()
        
    except Exception as e:
        print(f"❌ Error checking Neo4j dream data: {e}")

if __name__ == "__main__":
    print("🔍 Inspecting Sara's dream insights system...\n")
    inspect_dream_insights()
    check_neo4j_dream_data()
    print("\n✅ Inspection complete!")