-- ============================================================================
-- PostgreSQL Direct Triggers for Amnesia.io
-- ============================================================================
-- If you want your database to immediately push changes to Amnesia rather than
-- running a polling daemon, you can use these PostgreSQL-native trigger patterns.
-- Choose the method that best matches your PostgreSQL environment.

-- ----------------------------------------------------------------------------
-- OPTION 1: Using pg_net (Recommended for Neon, AWS RDS, Supabase)
-- pg_net is an asynchronous HTTP client for PostgreSQL. It will not block your
-- database transaction.
-- ----------------------------------------------------------------------------

-- 1. Ensure extension is installed
CREATE EXTENSION IF NOT EXISTS pg_net;

-- 2. Define the trigger function
CREATE OR REPLACE FUNCTION push_to_amnesia_pg_net()
RETURNS TRIGGER AS $$
DECLARE
    amnesia_url TEXT := 'http://localhost:8000/api/memory/ingest'; -- Replace with your Amnesia server URL
    amnesia_key TEXT := 'ak_YOUR_AMNESIA_API_KEY_HERE';            -- Replace with your API key
    payload JSONB;
BEGIN
    -- Prepare payload (map your columns to content)
    -- NEW.content or NEW.body etc.
    payload := jsonb_build_object(
        'content', NEW.content, -- Adjust column name here
        'confidence', 1.0
    );

    -- Fire asynchronous HTTP request
    PERFORM net.http_post(
        url := amnesia_url,
        body := payload,
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || amnesia_key,
            'Content-Type', 'application/json'
        )
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Bind function to target table
-- CREATE TRIGGER trg_amnesia_sync
-- AFTER INSERT ON posts -- Change 'posts' to your table
-- FOR EACH ROW
-- EXECUTE FUNCTION push_to_amnesia_pg_net();


-- ----------------------------------------------------------------------------
-- OPTION 2: Using PL/Python (Requires plpython3u extension)
-- Works if your database engine supports PL/Python.
-- Warning: Blocking synchronous call. Slows down inserts, but does not need pg_net.
-- ----------------------------------------------------------------------------

-- 1. Ensure language is enabled
-- CREATE LANGUAGE plpython3u;

-- 2. Define the trigger function
CREATE OR REPLACE FUNCTION push_to_amnesia_plpython()
RETURNS TRIGGER AS $$
    import json
    import urllib.request
    
    url = "http://localhost:8000/api/memory/ingest"
    api_key = "ak_YOUR_AMNESIA_API_KEY_HERE"
    
    # Extract the content from the row. TD["new"] contains the columns.
    # Adjust "content" to your table's content column.
    content = TD["new"].get("content")
    if not content:
        return None
        
    payload = {
        "content": content,
        "confidence": 1.0
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            pass # Success
    except Exception as e:
        # Log to postgres console/logs
        plpy.warning(f"Failed to sync to Amnesia: {e}")
        
    return None
$$ LANGUAGE plpython3u;

-- 3. Bind function to target table
-- CREATE TRIGGER trg_amnesia_sync_py
-- AFTER INSERT ON posts
-- FOR EACH ROW
-- EXECUTE FUNCTION push_to_amnesia_plpython();


-- ----------------------------------------------------------------------------
-- OPTION 3: Built-in LISTEN / NOTIFY (Non-blocking Pub/Sub, No Extensions Required)
-- Triggers publish an event to a channel, and an external daemon (like a python
-- listener) catches it and pushes it asynchronously.
-- ----------------------------------------------------------------------------

-- 1. Trigger function that broadcasts the row content or ID
CREATE OR REPLACE FUNCTION push_to_amnesia_notify()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
    -- Broadcast table name, ID, and content
    payload := json_build_object(
        'table', TG_TABLE_NAME,
        'id', NEW.id,
        'content', NEW.content -- Adjust column name here
    );
    
    PERFORM pg_notify('amnesia_sync_channel', payload::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Bind function to target table
-- CREATE TRIGGER trg_amnesia_notify
-- AFTER INSERT ON posts
-- FOR EACH ROW
-- EXECUTE FUNCTION push_to_amnesia_notify();

-- 3. Simple Python listener code snippet to run on your application server:
/*
import psycopg2
import select
import requests
import json

conn = psycopg2.connect("dbname=target_db user=username password=pass host=localhost")
conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

cursor = conn.cursor()
cursor.execute("LISTEN amnesia_sync_channel;")

print("Listening for DB notify events on 'amnesia_sync_channel'...")
while True:
    if select.select([conn],[],[], 5) == ([],[],[]):
        continue
    else:
        conn.poll()
        while conn.notifies:
            notify = conn.notifies.pop(0)
            payload = json.loads(notify.payload)
            print(f"Received notify: {payload}")
            
            # Sync to Amnesia
            res = requests.post(
                "http://localhost:8000/api/memory/ingest",
                json={"content": payload["content"], "confidence": 1.0},
                headers={"Authorization": "Bearer ak_YOUR_AMNESIA_API_KEY_HERE"}
            )
            print(f"Amnesia response status: {res.status_code}")
*/
