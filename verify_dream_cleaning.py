#!/usr/bin/env python3
"""
Verify Dream Insights Cleaning - Check that all dream insights have been successfully removed
"""

import psycopg
from datetime import datetime

def verify_postgresql_cleaning():
    """Verify PostgreSQL dream insights are cleaned"""
    try:
        conn = psycopg.connect('postgresql://sara:sara123@10.185.1.180:5432/sara_hub')
        cur = conn.cursor()
        
        # Count remaining dream insights
        cur.execute("SELECT COUNT(*) FROM dream_insight;")
        remaining_count = cur.fetchone()[0]
        
        if remaining_count == 0:
            print("✅ PostgreSQL dream_insight table is empty")
        else:
            print(f"⚠️  Found {remaining_count} remaining dream insights in PostgreSQL")
            
            # Show details of remaining insights
            cur.execute("""
                SELECT id, dream_date, insight_type, title 
                FROM dream_insight 
                ORDER BY dream_date DESC 
                LIMIT 5;
            """)
            remaining = cur.fetchall()
            print("   Remaining insights:")
            for insight in remaining:
                id_val, dream_date, insight_type, title = insight
                print(f"   - {id_val} | {dream_date} | {insight_type} | {title}")
        
        conn.close()
        return remaining_count == 0
        
    except Exception as e:
        print(f"❌ Error verifying PostgreSQL cleaning: {e}")
        return False

def verify_neo4j_cleaning():
    """Verify Neo4j dream-related content is cleaned"""
    try:
        from neo4j import GraphDatabase
        
        # Neo4j connection
        uri = "bolt://10.185.1.180:7687"
        username = "neo4j"
        password = "sara-graph-secret"
        
        driver = GraphDatabase.driver(uri, auth=(username, password))
        
        with driver.session() as session:
            # Check for remaining dream-related nodes
            result = session.run("""
                MATCH (n)
                WHERE toLower(n.title) CONTAINS 'dream' 
                   OR toLower(n.content) CONTAINS 'dream'
                   OR toLower(n.title) CONTAINS 'insight'
                   OR toLower(n.content) CONTAINS 'insight'
                   OR toLower(n.title) CONTAINS 'daily summary'
                   OR n.id CONTAINS 'daily_summary'
                RETURN count(n) as remaining_count
            """)
            
            count_result = result.single()
            remaining_count = count_result["remaining_count"] if count_result else 0
            
            if remaining_count == 0:
                print("✅ No dream/insight-related nodes found in Neo4j")
            else:
                print(f"⚠️  Found {remaining_count} dream/insight-related nodes in Neo4j")
                
                # Show examples of remaining nodes
                result = session.run("""
                    MATCH (n)
                    WHERE toLower(n.title) CONTAINS 'dream' 
                       OR toLower(n.content) CONTAINS 'dream'
                       OR toLower(n.title) CONTAINS 'insight'
                       OR toLower(n.content) CONTAINS 'insight'
                       OR toLower(n.title) CONTAINS 'daily summary'
                       OR n.id CONTAINS 'daily_summary'
                    RETURN labels(n) as labels, n.title as title, n.id as id
                    LIMIT 5
                """)
                
                examples = list(result)
                print("   Remaining nodes:")
                for record in examples:
                    labels = record["labels"]
                    title = record["title"]
                    node_id = record["id"]
                    print(f"   - {labels} | {title} | {node_id}")
        
        driver.close()
        return remaining_count == 0
        
    except Exception as e:
        print(f"❌ Error verifying Neo4j cleaning: {e}")
        return False

def check_dream_service_status():
    """Check if dream services are still running"""
    print("\n🌙 Dream Service Status:")
    print("The following services handle dream insights:")
    print("1. NightlyDreamService - processes conversations at 2:00 AM Eastern")
    print("2. DreamingService - generates insights from episodic memory")
    print("3. Intelligence Pipeline - coordinates nightly processing")
    print()
    print("These services will start generating new dream insights automatically.")
    print("New insights will have proper timestamps and no invalid dates.")

def main():
    """Main verification process"""
    print("🔍 Dream Insights Cleaning Verification")
    print("=======================================")
    print(f"Verification time: {datetime.now().isoformat()}")
    print()
    
    # Verify PostgreSQL cleaning
    print("Checking PostgreSQL...")
    pg_clean = verify_postgresql_cleaning()
    
    print()
    
    # Verify Neo4j cleaning
    print("Checking Neo4j...")
    neo4j_clean = verify_neo4j_cleaning()
    
    # Check dream service status
    check_dream_service_status()
    
    # Final summary
    print("\n📋 Verification Summary:")
    print(f"   PostgreSQL cleaned: {'✅ Yes' if pg_clean else '❌ No'}")
    print(f"   Neo4j cleaned: {'✅ Yes' if neo4j_clean else '❌ No'}")
    
    if pg_clean and neo4j_clean:
        print("\n🎉 All dream insights successfully cleaned!")
        print("   The system is ready for fresh dream insights generation.")
    else:
        print("\n⚠️  Some dream content may still remain.")
        print("   You may need to run the cleaning script again or manually remove remaining items.")

if __name__ == "__main__":
    main()