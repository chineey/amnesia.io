# Amnesia.io Ecosystem Vision

This guideline defines the high-level objective of the **amnesia.io** codebase for all AI coding agents working on this project.

## Core Objective

The ultimate goal of Amnesia.io is to serve as a **centralized, secure, user-owned personalization and memory database** for an ecosystem of diverse software applications. 

Rather than each software product building its own isolated profiling or memory storage layer, they will plug into Amnesia.io to personalize their experience.

## Integration Principles for Agents

When building scripts, integrations, or plugins for external software, adhere to these architectural guidelines:

1. **API Key Authentication**: External applications must interact with Amnesia via the user's raw API key (`Authorization: Bearer <key>`) over the HTTP integration routes (such as `/api/context` and `/api/memory/ingest`). Do not expose direct database credentials of the Amnesia PostgreSQL or Redis databases.
2. **Local Caching / Read-Side Sync**: To ensure third-party apps can fetch user context with low latency and without modifying their entire core logic, design sync scripts or local database bridges that write Amnesia's retrieved context back into a local cache/table of the external software's database.
3. **Decoupled Ingestion**: Watch for writes in the external software's database (such as new posts, notes, or queries) and asynchronously forward them to Amnesia's `/api/memory/ingest` endpoint so that the user's memory grows holistically across all connected apps.
4. **Privacy & Security**: Always respect user isolation. Ensure that the sync processes and database scripts handle keys and user IDs securely, never exposing raw credentials or crossing data boundaries.
