import os
import sys
import json
import tempfile
from http.server import BaseHTTPRequestHandler

# Ensure the bridge directory is on the path so we can import the module
bridge_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(bridge_dir)

from amnesia_db_bridge import AmnesiaDBBridge

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Simple auth check to ensure only authorized triggers (like Vercel Cron) call it
        auth_header = self.headers.get('Authorization')
        cron_secret = os.environ.get("CRON_SECRET")
        
        if cron_secret and auth_header != f"Bearer {cron_secret}":
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
            return

        # 2. Extract database and API details from Vercel Environment Variables
        amnesia_url = os.environ.get("AMNESIA_API_URL")
        amnesia_key = os.environ.get("AMNESIA_API_KEY")
        db_url = os.environ.get("DATABASE_URL")

        if not amnesia_key or not db_url:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Missing AMNESIA_API_KEY or DATABASE_URL environment variables in Vercel."
            }).encode('utf-8'))
            return

        # 3. Tables schema to sync (Customize this to match your Spotify database)
        tables_to_sync = [
            {
                "table_name": "user_feedback",
                "id_column": "id",
                "content_column": "feedback_text",
                "timestamp_column": "created_at",
                "confidence": 1.0
            }
        ]

        # 4. Construct a temporary config JSON for the bridge script
        config_data = {
            "amnesia_api_url": amnesia_url,
            "amnesia_api_key": amnesia_key,
            "target_db_uri": db_url,
            "tables_to_sync": tables_to_sync
        }

        # Create a temporary config file
        fd, temp_config_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, 'w') as tmp:
                json.dump(config_data, tmp)

            # 5. Initialize the DB Bridge and run a single sync cycle
            bridge = AmnesiaDBBridge(temp_config_path)
            bridge.run_once()

            # Respond with success
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True, 
                "message": "Amnesia DB synchronization completed successfully."
            }).encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": str(e)
            }).encode('utf-8'))
        finally:
            # Clean up the temporary config file
            if os.path.exists(temp_config_path):
                os.remove(temp_config_path)
