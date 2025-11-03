"""
Add food database table for tracking individual foods with nutrition
"""
import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg URL
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

conn = psycopg.connect(db_url)
cur = conn.cursor()

# Create food_database table for storing individual foods
cur.execute("""
    CREATE TABLE IF NOT EXISTS food_database (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL,
        name VARCHAR(255) NOT NULL,
        brand VARCHAR(255),
        serving_size FLOAT NOT NULL DEFAULT 1,
        serving_unit VARCHAR(50) NOT NULL DEFAULT 'serving',
        calories FLOAT,
        protein FLOAT,
        carbs FLOAT,
        fats FLOAT,
        fiber FLOAT,
        sugar FLOAT,
        sodium FLOAT,
        is_custom BOOLEAN DEFAULT true,
        source VARCHAR(50) DEFAULT 'user',
        barcode VARCHAR(50),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE
    )
""")

# Create index for faster searches
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_food_database_user_name
    ON food_database(user_id, name)
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_food_database_barcode
    ON food_database(barcode) WHERE barcode IS NOT NULL
""")

# Update food_log table to store detailed food items with nutrition
cur.execute("""
    ALTER TABLE food_log
    ADD COLUMN IF NOT EXISTS detailed_items JSONB
""")

conn.commit()
cur.close()
conn.close()

print("✅ Food database tables created successfully")
