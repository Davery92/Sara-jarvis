#!/usr/bin/env python3
"""
Clean Dream Insights - Remove all existing dream insights to get a fresh start

This script will:
1. Back up existing dream insights to a JSON file
2. Remove all dream insights from the PostgreSQL database 
3. Check Neo4j for any dream-related content and optionally clean it
4. Provide a summary of what was cleaned
"""

import psycopg
import json
from datetime import datetime
import os

def backup_dream_insights():
    """Create a backup of all existing dream insights"""
    try:
        conn = psycopg.connect('postgresql://sara:sara123@10.185.1.180:5432/sara_hub')
        cur = conn.cursor()
        
        # Get all dream insights
        cur.execute("""
            SELECT id, user_id, dream_date, insight_type, confidence, title, content, 
                   related_episodes, surfaced_at, user_feedback, created_at
            FROM dream_insight
            ORDER BY dream_date;
        """)
        
        insights = cur.fetchall()
        
        # Convert to backup format
        backup_data = {
            'backup_date': datetime.now().isoformat(),
            'total_insights': len(insights),
            'insights': []
        }
        
        for insight in insights:
            backup_data['insights'].append({
                'id': insight[0],
                'user_id': insight[1], 
                'dream_date': insight[2].isoformat() if insight[2] else None,
                'insight_type': insight[3],
                'confidence': insight[4],
                'title': insight[5],
                'content': insight[6],
                'related_episodes': insight[7],
                'surfaced_at': insight[8].isoformat() if insight[8] else None,
                'user_feedback': insight[9],
                'created_at': insight[10].isoformat() if insight[10] else None
            })
        
        # Save backup file
        backup_filename = f"dream_insights_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_filename, 'w') as f:
            json.dump(backup_data, f, indent=2)
        
        print(f"✅ Backed up {len(insights)} dream insights to: {backup_filename}")
        conn.close()
        return backup_filename, len(insights)
        
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        return None, 0

def clean_postgresql_dream_insights():
    """Remove all dream insights from PostgreSQL"""
    try:
        conn = psycopg.connect('postgresql://sara:sara123@10.185.1.180:5432/sara_hub')
        cur = conn.cursor()
        
        # Count before deletion
        cur.execute("SELECT COUNT(*) FROM dream_insight;")
        count_before = cur.fetchone()[0]
        
        if count_before == 0:
            print("ℹ️  No dream insights found in PostgreSQL")
            conn.close()
            return 0
        
        # Delete all dream insights
        cur.execute("DELETE FROM dream_insight;")
        deleted_count = cur.rowcount
        
        # Commit the transaction
        conn.commit()
        
        # Verify deletion
        cur.execute("SELECT COUNT(*) FROM dream_insight;")
        count_after = cur.fetchone()[0]
        
        print(f"✅ Deleted {deleted_count} dream insights from PostgreSQL")
        print(f"   Before: {count_before}, After: {count_after}")
        
        conn.close()
        return deleted_count
        
    except Exception as e:
        print(f"❌ Error cleaning PostgreSQL dream insights: {e}")
        return 0

def check_and_clean_neo4j_dream_content():
    """Check Neo4j for dream-related content and optionally clean it"""
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
                   OR toLower(n.title) CONTAINS 'daily summary'
                   OR n.id CONTAINS 'daily_summary'
                RETURN count(n) as dream_node_count
            """)
            
            count_result = result.single()
            dream_node_count = count_result["dream_node_count"] if count_result else 0
            
            print(f"🧠 Found {dream_node_count} dream/insight-related nodes in Neo4j")
            
            if dream_node_count > 0:
                # Show some examples
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
                print("   Examples:")
                for record in examples:
                    labels = record["labels"]
                    title = record["title"]
                    node_id = record["id"]
                    print(f"   - {labels} | {title} | {node_id}")
                
                # Ask user if they want to clean Neo4j too
                response = input(f"\nWould you like to delete these {dream_node_count} Neo4j nodes? (y/N): ")
                if response.lower() == 'y':
                    # Delete dream-related nodes
                    result = session.run("""
                        MATCH (n)
                        WHERE toLower(n.title) CONTAINS 'dream' 
                           OR toLower(n.content) CONTAINS 'dream'
                           OR toLower(n.title) CONTAINS 'insight'
                           OR toLower(n.content) CONTAINS 'insight'
                           OR toLower(n.title) CONTAINS 'daily summary'
                           OR n.id CONTAINS 'daily_summary'
                        DETACH DELETE n
                        RETURN count(*) as deleted_count
                    """)
                    
                    delete_result = result.single()
                    deleted_count = delete_result["deleted_count"] if delete_result else 0
                    print(f"✅ Deleted {deleted_count} dream/insight nodes from Neo4j")
                    return deleted_count
                else:
                    print("ℹ️  Skipped Neo4j cleaning")
                    return 0
            else:
                print("ℹ️  No dream-related nodes found in Neo4j")
                return 0
        
        driver.close()
        
    except Exception as e:
        print(f"❌ Error checking/cleaning Neo4j dream content: {e}")
        return 0

def main():
    """Main cleaning process"""
    print("🧹 Dream Insights Cleaning Tool")
    print("===============================")
    print()
    
    # Confirm with user
    print("This will:")
    print("1. Create a backup of all existing dream insights") 
    print("2. Delete all dream insights from PostgreSQL")
    print("3. Check Neo4j for dream-related content")
    print()
    
    response = input("Are you sure you want to continue? (y/N): ")
    if response.lower() != 'y':
        print("❌ Operation cancelled")
        return
    
    print("\n🔄 Starting cleaning process...\n")
    
    # Step 1: Backup
    backup_file, backup_count = backup_dream_insights()
    if backup_count == 0:
        print("ℹ️  No dream insights found to clean")
        return
    
    # Step 2: Clean PostgreSQL
    deleted_pg_count = clean_postgresql_dream_insights()
    
    # Step 3: Check Neo4j
    deleted_neo4j_count = check_and_clean_neo4j_dream_content()
    
    # Summary
    print("\n📋 Cleaning Summary:")
    print(f"   PostgreSQL insights deleted: {deleted_pg_count}")
    print(f"   Neo4j nodes deleted: {deleted_neo4j_count}")
    if backup_file:
        print(f"   Backup saved to: {backup_file}")
    
    print("\n✅ Dream insights cleaning complete!")
    print("   The system is now ready for a fresh start with dream insights.")

if __name__ == "__main__":
    main()