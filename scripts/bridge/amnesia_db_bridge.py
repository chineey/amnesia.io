#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional
import requests
from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("amnesia.db_bridge")

class AmnesiaDBBridge:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.engine = None
        self.load_config()
        self.init_db_connection()
        self.init_bridge_schema()

    def load_config(self):
        if not os.path.exists(self.config_path):
            logger.error(f"Configuration file not found: {self.config_path}")
            sys.exit(1)
        try:
            with open(self.config_path, "r") as f:
                self.config = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to parse config file: {e}")
            sys.exit(1)

        # Validate basic config keys
        required_keys = ["amnesia_api_url", "amnesia_api_key", "target_db_uri"]
        for key in required_keys:
            if key not in self.config or not self.config[key]:
                logger.error(f"Missing required configuration key: {key}")
                sys.exit(1)

    def init_db_connection(self):
        db_uri = self.config["target_db_uri"]
        logger.info(f"Connecting to target database: {db_uri.split('@')[-1] if '@' in db_uri else db_uri}") # Obfuscate credentials in logs
        try:
            self.engine = create_engine(db_uri)
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Successfully connected to target database.")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            sys.exit(1)

    def init_bridge_schema(self):
        """Creates the metadata and cache tables in the target database if they do not exist."""
        db_type = self.engine.dialect.name
        logger.info(f"Initializing bridge schema in target database ({db_type})...")

        # Table definitions:
        # 1. amnesia_sync_metadata: tracks the last synced ID or timestamp for configured tables
        # 2. amnesia_context_cache: stores the fetched profile facts and preferences locally
        queries = []

        if db_type == "sqlite":
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_sync_metadata (
                table_name TEXT PRIMARY KEY,
                last_synced_id TEXT,
                last_synced_timestamp TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_context_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
        elif db_type == "postgresql":
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_sync_metadata (
                table_name VARCHAR PRIMARY KEY,
                last_synced_id VARCHAR,
                last_synced_timestamp TIMESTAMP WITH TIME ZONE,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """)
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_context_cache (
                key VARCHAR PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """)
        else:
            # Default to standard SQL definitions compatible with MySQL, etc.
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_sync_metadata (
                table_name VARCHAR(255) PRIMARY KEY,
                last_synced_id VARCHAR(255),
                last_synced_timestamp DATETIME,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """)
            queries.append("""
            CREATE TABLE IF NOT EXISTS amnesia_context_cache (
                key VARCHAR(255) PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """)

        try:
            with self.engine.begin() as conn:
                for q in queries:
                    conn.execute(text(q))
            logger.info("Bridge metadata schema verified/created successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize bridge schema: {e}")
            sys.exit(1)

    def test_amnesia_connection(self) -> bool:
        """Tests connection to Amnesia API endpoints."""
        url = self.config["amnesia_api_url"].rstrip("/")
        key = self.config["amnesia_api_key"]
        headers = {"Authorization": f"Bearer {key}"}

        # 1. Health check
        try:
            res_h = requests.get(f"{url}/api/health", timeout=10)
            if res_h.status_code != 200:
                logger.error(f"Health check failed with status: {res_h.status_code}")
                return False
        except Exception as e:
            logger.error(f"Could not connect to Amnesia health endpoint: {e}")
            return False

        # 2. Key Auth verification via /api/profile
        try:
            res_auth = requests.get(f"{url}/api/profile", headers=headers, timeout=10)
            if res_auth.status_code == 401:
                logger.error("Authentication failed: Invalid Amnesia API key.")
                return False
            elif res_auth.status_code != 200:
                logger.error(f"Profile fetch failed with status: {res_auth.status_code}")
                return False
            logger.info("Successfully authenticated with Amnesia API.")
            return True
        except Exception as e:
            logger.error(f"Failed to authenticate with Amnesia API: {e}")
            return False

    def get_sync_state(self, table_name: str) -> Dict[str, Any]:
        """Fetches the last sync markers for a table."""
        with self.engine.connect() as conn:
            stmt = text("""
                SELECT last_synced_id, last_synced_timestamp 
                FROM amnesia_sync_metadata 
                WHERE table_name = :table_name
            """)
            row = conn.execute(stmt, {"table_name": table_name}).fetchone()
            if row:
                return {
                    "last_synced_id": row[0],
                    "last_synced_timestamp": row[1]
                }
            return {"last_synced_id": None, "last_synced_timestamp": None}

    def update_sync_state(self, table_name: str, last_id: Optional[str], last_ts: Optional[Any]):
        """Saves the last synced checkpoints to DB."""
        # Convert timestamp to string if SQLite
        db_type = self.engine.dialect.name
        ts_val = last_ts
        if db_type == "sqlite" and isinstance(last_ts, (datetime.datetime, datetime.date)):
            ts_val = last_ts.isoformat()

        updated_at = datetime.datetime.now()
        if db_type == "sqlite":
            updated_at = updated_at.isoformat()

        with self.engine.begin() as conn:
            # Check if row exists
            check_stmt = text("SELECT 1 FROM amnesia_sync_metadata WHERE table_name = :table_name")
            exists = conn.execute(check_stmt, {"table_name": table_name}).fetchone()

            if exists:
                stmt = text("""
                    UPDATE amnesia_sync_metadata 
                    SET last_synced_id = :last_id, 
                        last_synced_timestamp = :last_ts, 
                        updated_at = :updated_at 
                    WHERE table_name = :table_name
                """)
            else:
                stmt = text("""
                    INSERT INTO amnesia_sync_metadata (table_name, last_synced_id, last_synced_timestamp, updated_at) 
                    VALUES (:table_name, :last_id, :last_ts, :updated_at)
                """)

            conn.execute(stmt, {
                "table_name": table_name,
                "last_id": str(last_id) if last_id is not None else None,
                "last_ts": ts_val,
                "updated_at": updated_at
            })

    def sync_table(self, mapping: Dict[str, Any]):
        """Polls and syncs a specific table."""
        table_name = mapping["table_name"]
        id_col = mapping["id_column"]
        content_col = mapping["content_column"]
        ts_col = mapping.get("timestamp_column")
        confidence = mapping.get("confidence", 1.0)

        state = self.get_sync_state(table_name)
        last_id = state["last_synced_id"]
        last_ts = state["last_synced_timestamp"]

        logger.info(f"Syncing table '{table_name}' starting from checkpoint (ID: {last_id}, Timestamp: {last_ts})")

        # Determine filtering query
        query_parts = [f"SELECT {id_col}, {content_col}"]
        params = {}

        if ts_col:
            query_parts.append(f", {ts_col}")

        query_parts.append(f"FROM {table_name}")

        # Check filter
        filters = []
        if last_id is not None:
            # Check if last_id is numeric to handle comparison properly
            is_numeric = False
            try:
                int(last_id)
                is_numeric = True
            except ValueError:
                pass

            if is_numeric:
                filters.append(f"{id_col} > :last_id")
                params["last_id"] = int(last_id)
            else:
                filters.append(f"{id_col} > :last_id")
                params["last_id"] = last_id
        elif last_ts is not None and ts_col:
            filters.append(f"{ts_col} > :last_ts")
            params["last_ts"] = last_ts

        if filters:
            query_parts.append("WHERE " + " AND ".join(filters))

        # Order of operations
        if ts_col:
            query_parts.append(f"ORDER BY {ts_col} ASC, {id_col} ASC")
        else:
            query_parts.append(f"ORDER BY {id_col} ASC")

        select_query = " ".join(query_parts)

        new_rows = []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(select_query), params)
                new_rows = result.fetchall()
        except Exception as e:
            logger.error(f"Error querying table '{table_name}': {e}")
            return

        if not new_rows:
            logger.info(f"Table '{table_name}' is already up-to-date. 0 rows synced.")
            return

        logger.info(f"Found {len(new_rows)} new rows to sync for '{table_name}'")

        url = self.config["amnesia_api_url"].rstrip("/")
        key = self.config["amnesia_api_key"]
        headers = {"Authorization": f"Bearer {key}"}

        success_count = 0
        latest_id = last_id
        latest_ts = last_ts

        for row in new_rows:
            row_id = row[0]
            content = row[1]
            row_ts = row[2] if len(row) > 2 else None

            if not content or not str(content).strip():
                # Skip empty records
                latest_id = row_id
                if row_ts:
                    latest_ts = row_ts
                continue

            # Ingest to Amnesia
            payload = {
                "content": str(content).strip(),
                "confidence": float(confidence)
            }

            try:
                res = requests.post(f"{url}/api/memory/ingest", json=payload, headers=headers, timeout=10)
                if res.status_code == 200:
                    success_count += 1
                    latest_id = row_id
                    if row_ts:
                        latest_ts = row_ts
                else:
                    logger.warning(f"Failed to ingest row {row_id} from table '{table_name}': HTTP {res.status_code} - {res.text}")
                    # Stop sync for this table on first failure to maintain order consistency
                    break
            except Exception as e:
                logger.error(f"HTTP request error during ingestion of row {row_id}: {e}")
                break

        # Save sync progress if we succeeded on some entries
        if latest_id != last_id or latest_ts != last_ts:
            self.update_sync_state(table_name, latest_id, latest_ts)
            logger.info(f"Synchronized {success_count}/{len(new_rows)} records for '{table_name}'. Updated checkpoint.")

    def sync_all_tables(self):
        """Iterates and syncs all configured tables."""
        mappings = self.config.get("tables_to_sync", [])
        if not mappings:
            logger.warning("No tables configured for synchronization in 'tables_to_sync'.")
            return

        for mapping in mappings:
            try:
                self.sync_table(mapping)
            except Exception as e:
                logger.error(f"Unhandled error syncing table '{mapping.get('table_name')}': {e}")

    def fetch_and_cache_context(self):
        """Fetches profile facts/preferences from Amnesia and caches them in the target database."""
        logger.info("Fetching latest user profile context from Amnesia...")
        url = self.config["amnesia_api_url"].rstrip("/")
        key = self.config["amnesia_api_key"]
        headers = {"Authorization": f"Bearer {key}"}

        # 1. Fetch Profile
        profile_data = None
        try:
            res = requests.get(f"{url}/api/profile", headers=headers, timeout=10)
            if res.status_code == 200:
                profile_data = res.json()
            else:
                logger.error(f"Failed to fetch profile context from Amnesia: HTTP {res.status_code}")
        except Exception as e:
            logger.error(f"Error fetching profile context: {e}")

        # 2. Fetch Memories (optional context fallback)
        memories_data = None
        try:
            res_m = requests.get(f"{url}/api/memories", headers=headers, timeout=10)
            if res_m.status_code == 200:
                memories_data = res_m.json()
        except Exception as e:
            logger.error(f"Error fetching memories context: {e}")

        if profile_data is None:
            logger.warning("Aborting context cache update due to empty profile response.")
            return

        # Prepare payload to write back
        cache_writes = {
            "core_profile": json.dumps(profile_data),
            "last_sync_time": datetime.datetime.now().isoformat()
        }
        if memories_data is not None:
            cache_writes["memories"] = json.dumps(memories_data)

        # Write to target database cache table
        db_type = self.engine.dialect.name
        try:
            with self.engine.begin() as conn:
                for k, v in cache_writes.items():
                    updated_at = datetime.datetime.now()
                    if db_type == "sqlite":
                        updated_at = updated_at.isoformat()

                    # Upsert implementation
                    check_stmt = text("SELECT 1 FROM amnesia_context_cache WHERE key = :key")
                    exists = conn.execute(check_stmt, {"key": k}).fetchone()

                    if exists:
                        stmt = text("""
                            UPDATE amnesia_context_cache 
                            SET value = :value, updated_at = :updated_at 
                            WHERE key = :key
                        """)
                    else:
                        stmt = text("""
                            INSERT INTO amnesia_context_cache (key, value, updated_at) 
                            VALUES (:key, :value, :updated_at)
                        """)

                    conn.execute(stmt, {"key": k, "value": v, "updated_at": updated_at})
            logger.info("Successfully updated local context cache in target database.")
        except Exception as e:
            logger.error(f"Failed to write context cache to target database: {e}")

    def run_once(self):
        """Performs a single sync cycle."""
        logger.info("Starting database sync execution cycle...")
        if not self.test_amnesia_connection():
            logger.error("Amnesia connection test failed. Aborting execution cycle.")
            return
        
        self.sync_all_tables()
        self.fetch_and_cache_context()
        logger.info("Sync execution cycle complete.")

    def run_daemon(self, sync_interval: int, writeback_interval: int):
        """Runs the bridge in a background daemon loop."""
        logger.info(f"Starting Amnesia DB Bridge Daemon (Sync every {sync_interval}s, Writeback every {writeback_interval}s)")
        
        last_writeback_time = 0.0
        
        while True:
            try:
                # 1. Test Amnesia connection
                connected = self.test_amnesia_connection()
                if not connected:
                    logger.warning("Cannot establish connection to Amnesia. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue

                # 2. Sync tables
                self.sync_all_tables()

                # 3. Periodically fetch and cache context
                current_time = time.time()
                if current_time - last_writeback_time >= writeback_interval:
                    self.fetch_and_cache_context()
                    last_writeback_time = current_time

            except KeyboardInterrupt:
                logger.info("Daemon execution terminated by user.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in daemon loop: {e}")

            time.sleep(sync_interval)

def main():
    parser = argparse.ArgumentParser(description="Amnesia.io Database Integration Bridge")
    parser.add_argument(
        "--config", 
        default="bridge_config.json", 
        help="Path to configuration JSON file (default: bridge_config.json)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--sync-now", 
        action="store_true", 
        help="Perform a single synchronization run and exit"
    )
    group.add_argument(
        "--daemon", 
        action="store_true", 
        help="Run continuously in background daemon mode"
    )
    group.add_argument(
        "--test-connection", 
        action="store_true", 
        help="Verify connection to target database and Amnesia API, then exit"
    )

    args = parser.parse_args()

    bridge = AmnesiaDBBridge(args.config)

    if args.test_connection:
        logger.info("Testing connection pipelines...")
        amnesia_ok = bridge.test_amnesia_connection()
        if amnesia_ok:
            logger.info("SUCCESS: All systems connected.")
            sys.exit(0)
        else:
            logger.error("FAILURE: Connection verify failed.")
            sys.exit(1)

    elif args.sync_now:
        bridge.run_once()
        sys.exit(0)

    elif args.daemon:
        sync_interval = bridge.config.get("sync_interval_seconds", 60)
        writeback_interval = bridge.config.get("writeback_interval_seconds", 300)
        bridge.run_daemon(sync_interval, writeback_interval)

if __name__ == "__main__":
    main()
