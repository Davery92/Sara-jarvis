"""
Quick script to query Neo4j and see what data was stored
"""
import os
from neo4j import GraphDatabase

os.environ['NEO4J_URI'] = "bolt://10.185.1.180:7687"
os.environ['NEO4J_USER'] = "neo4j"
os.environ['NEO4J_PASSWORD'] = "sara-graph-secret"

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
)

with driver.session() as session:
    # Count all nodes by label
    result = session.run("MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC")

    print("\\n=== Neo4j Node Counts ===")
    for record in result:
        print(f"{record['type']}: {record['count']}")

    # Count all relationships
    result = session.run("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC")

    print("\\n=== Neo4j Relationship Counts ===")
    for record in result:
        print(f"{record['rel_type']}: {record['count']}")

    # Show sample content node
    result = session.run("MATCH (c:Content) RETURN c.title, c.content_type LIMIT 5")

    print("\\n=== Sample Content Nodes ===")
    for record in result:
        print(f"- {record['c.title']} ({record['c.content_type']})")

driver.close()
