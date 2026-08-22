#!/usr/bin/env python3
import http.server
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

PORT = 9876
MOCK_API_KEY = "ak_test_key_12345"

# Mock Server to intercept Amnesia API requests
class MockAmnesiaHandler(http.server.BaseHTTPRequestHandler):
    ingested_memories = []
    auth_verified = False

    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "version": "1.0.0"}).encode())
        elif self.path == "/api/profile":
            # Check auth
            auth_header = self.headers.get("Authorization", "")
            if auth_header != f"Bearer {MOCK_API_KEY}":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            MockAmnesiaHandler.auth_verified = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            profile = {
                "facts": [
                    {"content": "Mock User Name is Bob.", "confidence": 1.0},
                    {"content": "Mock User prefers Python over Java.", "confidence": 1.0}
                ],
                "preferences": [
                    {"content": "Mock User prefers concise emails.", "confidence": 0.9}
                ],
                "events": []
            }
            self.wfile.write(json.dumps(profile).encode())
        elif self.path == "/api/memories":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([]).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/memory/ingest":
            # Check auth
            auth_header = self.headers.get("Authorization", "")
            if auth_header != f"Bearer {MOCK_API_KEY}":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))

            MockAmnesiaHandler.ingested_memories.append(payload)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence HTTP logs for cleaner output
        pass

def run_mock_server():
    server_address = ('', PORT)
    httpd = http.server.HTTPServer(server_address, MockAmnesiaHandler)
    httpd.serve_forever()

def main():
    print("====================================================")
    print("Amnesia DB Bridge Test & Verification Runner")
    print("====================================================")

    # 1. Start the Mock Server in a background thread
    server_thread = threading.Thread(target=run_mock_server, daemon=True)
    server_thread.start()
    print(f"Mock Amnesia API Server started on port {PORT}")
    time.sleep(1) # Let the server bind

    # 2. Setup mock target database
    db_path = "test_software.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    print(f"Creating mock software database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Insert test rows to sync
    test_posts = [
        "Today I worked on my new project ecosystem.",
        "Green tea is better than black coffee in the evening.",
        "Must verify that the PL/pgSQL database trigger functions correctly."
    ]
    for p in test_posts:
        cursor.execute("INSERT INTO posts (content) VALUES (?)", (p,))
    conn.commit()
    conn.close()
    print("Mock database populated with 3 test posts.")

    # 3. Create test bridge config
    config_path = "test_bridge_config.json"
    config_data = {
        "amnesia_api_url": f"http://localhost:{PORT}",
        "amnesia_api_key": MOCK_API_KEY,
        "target_db_uri": f"sqlite:///{db_path}",
        "sync_interval_seconds": 5,
        "writeback_interval_seconds": 10,
        "tables_to_sync": [
            {
                "table_name": "posts",
                "id_column": "id",
                "content_column": "content",
                "timestamp_column": "created_at",
                "confidence": 0.95
            }
        ]
    }
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
    print(f"Generated test configuration at {config_path}")

    # 4. Invoke the bridge script in test-connection mode
    bridge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amnesia_db_bridge.py")
    
    print("\n[Test 1] Testing Connection Mode...")
    proc_test = subprocess.run([
        sys.executable, bridge_script,
        "--config", config_path,
        "--test-connection"
    ], capture_output=True, text=True)
    
    print(f"Connection Test Exit Code: {proc_test.returncode}")
    if proc_test.returncode != 0:
        print(f"Stdout:\n{proc_test.stdout}")
        print(f"Stderr:\n{proc_test.stderr}")
        print("ERROR: Connection test failed.")
        sys.exit(1)
    print("SUCCESS: Connection test passed.")

    # 5. Invoke bridge in sync-now mode
    print("\n[Test 2] Testing Synchronization Mode...")
    proc_sync = subprocess.run([
        sys.executable, bridge_script,
        "--config", config_path,
        "--sync-now"
    ], capture_output=True, text=True)

    print(f"Sync Test Exit Code: {proc_sync.returncode}")
    if proc_sync.returncode != 0:
        print(f"Stdout:\n{proc_sync.stdout}")
        print(f"Stderr:\n{proc_sync.stderr}")
        print("ERROR: Sync execution failed.")
        sys.exit(1)
    print("SUCCESS: Sync execution completed.")

    # 6. Verify sync results
    print("\n[Verification] Checking Results...")

    # Check mock server side
    print(f"Total memories ingested by mock Amnesia API: {len(MockAmnesiaHandler.ingested_memories)}")
    for idx, mem in enumerate(MockAmnesiaHandler.ingested_memories):
        print(f"  Ingest #{idx+1}: Content='{mem['content']}' | Confidence={mem['confidence']}")

    if len(MockAmnesiaHandler.ingested_memories) != 3:
        print("ERROR: Expected 3 ingested memories, got direct count mismatch.")
        sys.exit(1)

    # Check database side metadata updates
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Verify amnesia_sync_metadata
    cursor.execute("SELECT table_name, last_synced_id FROM amnesia_sync_metadata")
    metadata = cursor.fetchall()
    print(f"Sync Metadata row: {metadata}")
    if not metadata or metadata[0][0] != "posts" or int(metadata[0][1]) != 3:
        print("ERROR: amnesia_sync_metadata was not updated correctly.")
        sys.exit(1)

    # Verify amnesia_context_cache (writeback check)
    cursor.execute("SELECT key, value FROM amnesia_context_cache WHERE key = 'core_profile'")
    cache_row = cursor.fetchone()
    if not cache_row:
        print("ERROR: amnesia_context_cache does not contain 'core_profile'.")
        sys.exit(1)

    cached_profile = json.loads(cache_row[1])
    print(f"Cached Profile from DB: {cached_profile}")
    if "Mock User Name is Bob." not in [f["content"] for f in cached_profile.get("facts", [])]:
        print("ERROR: Cached profile contents did not match expected values.")
        sys.exit(1)

    conn.close()
    print("SUCCESS: Database schema state checked. Cache and Metadata correct.")

    # 7. Cleanup
    print("\nCleaning up temporary test files...")
    os.remove(db_path)
    os.remove(config_path)
    print("Cleanup completed.")
    print("====================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("====================================================")

if __name__ == "__main__":
    main()
