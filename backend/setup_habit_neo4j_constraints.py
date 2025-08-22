#!/usr/bin/env python3
"""
Setup Neo4j constraints for habit tracking system
"""

import os
import asyncio
from neo4j import GraphDatabase


async def setup_habit_constraints():
    """Create Neo4j constraints for habit entities"""
    
    # Neo4j connection
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://10.185.1.180:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "sara-graph-secret")
    
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    constraints = [
        # Habit entity constraints
        "CREATE CONSTRAINT unique_habit IF NOT EXISTS FOR (h:Habit) REQUIRE h.id IS UNIQUE",
        "CREATE CONSTRAINT unique_habit_instance IF NOT EXISTS FOR (i:HabitInstance) REQUIRE i.id IS UNIQUE", 
        "CREATE CONSTRAINT unique_habit_item IF NOT EXISTS FOR (item:HabitItem) REQUIRE item.id IS UNIQUE",
        "CREATE CONSTRAINT unique_habit_log IF NOT EXISTS FOR (log:HabitLog) REQUIRE log.id IS UNIQUE",
        
        # Indexes for performance
        "CREATE INDEX habit_user_index IF NOT EXISTS FOR (h:Habit) ON (h.user_id)",
        "CREATE INDEX habit_instance_date_index IF NOT EXISTS FOR (i:HabitInstance) ON (i.date)",
        "CREATE INDEX habit_log_timestamp_index IF NOT EXISTS FOR (log:HabitLog) ON (log.timestamp)",
    ]
    
    try:
        with driver.session() as session:
            print("🔧 Setting up Neo4j constraints for habit tracking...")
            
            for constraint in constraints:
                try:
                    result = session.run(constraint)
                    print(f"✅ Applied: {constraint}")
                except Exception as e:
                    if "already exists" in str(e).lower() or "constraint already exists" in str(e).lower():
                        print(f"⚠️  Already exists: {constraint}")
                    else:
                        print(f"❌ Failed: {constraint} - {e}")
            
            print("🎉 Neo4j habit constraints setup complete!")
            
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
    finally:
        driver.close()


if __name__ == "__main__":
    asyncio.run(setup_habit_constraints())