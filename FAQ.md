# amnesia.io — FAQ: Deployment & Memory Architecture

This document answers common questions regarding the deployment, scaling, user isolation, and token budget mechanisms of **amnesia.io**.

---

## 🚀 1. Deployment & Keep-Alive

### How does the Render deployment work?
By default, the project is configured for **Unified (Single-Service) Deployment**. 
* **One Web Service**: Instead of managing a separate frontend static site and a backend python web service, the Python backend compiles the React frontend assets (`npm run build`) during the build step and hosts the compiled React site directly at the `/` root route.
* **No CORS or Hardcoded Endpoints**: All API requests (`/api/*`) are served on the same domain and port, eliminating cross-origin (CORS) configurations and the need to hardcode external backend domains in the frontend code.

### How do I bypass Render's credit card requirement?
Render requires credit card details for Blueprint (`render.yaml`) deployments. To deploy for free without a card:
1. Create a manual **Web Service** in the Render Dashboard.
2. Select your repository.
3. Configure the following parameters:
   * **Language**: `Python`
   * **Build Command**: `cd frontend && npm install && npm run build && cd .. && pip install -r backend/requirements.txt`
   * **Start Command**: `python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
   * **Instance Type**: `Free`
4. Add your API keys and connection strings under **Advanced -> Environment Variables**.

### How do I prevent the Render Free service from sleeping?
Render's Free tier spins down (goes to sleep) after 15 minutes of inactivity. 
To keep it warm and active, use a free cron service (such as [cron-job.org](https://cron-job.org/) or [UptimeRobot](https://uptimerobot.com/)) to send an HTTP GET request to your health check endpoint:
```http
https://your-app-name.onrender.com/api/health
```
Schedule this to ping your service **every 10 minutes** to keep it active and avoid cold starts.

---

## 🔒 2. User Isolation & Local Storage

### If someone else visits my deployed link, will they see my memory?
**No.** The application enforces secure authentication and strict tenant isolation:
1. **User Accounts & Sign In**: Visitors must register or log in using their email and password.
2. **JWT Session Token**: Upon logging in, the backend issues a JSON Web Token (JWT) cryptographically signed with a server-side secret key. The token is saved in the browser's local storage under `amnesia_token`.
3. **Secure Verification**: When the frontend requests memories or profile data, it passes the JWT token in the `Authorization` header. The backend validates this token to extract the user's secure UUID, querying only database records matching that user.
4. **Session Cache**: The active chat thread is isolated in Redis using a session ID unique to that browser tab and session.

### Can my browser's local storage get full?
**No.** Browser local storage supports up to 5MB–10MB of data. The React frontend only stores your `amnesia_token` JWT string, which uses **less than 300 bytes**. Storing actual episodic memories and core profile facts is handled entirely on the server's PostgreSQL database, not in your browser.

### How do I connect external applications (like GenPost) to my memory?
Amnesia.io provides long-lived API keys for third-party integrations:
1. In the application header, click **"Connect GenPost"** (or view your profile after signing up) to reveal your personal Amnesia API key (prefixed with `ak_`).
2. Paste this API key into the target application's settings.
3. The external app can then authenticate its calls to Amnesia endpoints (such as `GET /api/context` to retrieve profile facts, `POST /api/memory/ingest` to save memories, or `POST /api/profile/facts` to update core profile stats) by passing this key in its request headers.

### Are integration API keys stored securely?
**Yes.** The backend never stores API keys in plaintext. It stores only a SHA-256 hash (`api_key_hash`) of your key in the database. When an API call is made, the backend hashes the incoming key and compares it against the database hash. This means even if the database is compromised, your API keys cannot be recovered.

---

## 🧠 3. Token Budgets & Memory Limits

### What is the "Token Cap Enforcement"?
FastAPI applies an **800-token cap** on the prompt sent to the LLM. This keeps calls fast and cost-effective. Here is the breakdown:

| Budget Item | Token Size | Description |
| :--- | :--- | :--- |
| **Total Context Limit** | `800` | The total window budget (roughly 600 words). |
| **Core Profile Injected** | Variable (e.g., `14`) | Structured facts and preferences (always included). |
| **Redis History Tail** | Up to `150` | The active chat messages from the current session. |
| **Semantic Episodic Injected** | Variable (e.g., `213`) | Relevant past snippets loaded from the database. |
| **Remaining Budget** | Leftover space (e.g., `423`) | Space for your current message and the AI's response. |

### What happens when the token cap runs out?
If your conversation history and memories grow larger than the 800-token cap, the system prioritizes what to pack:
1. The **Core Profile** and recent **Working Memory** are packed first.
2. The remaining space is filled with **Episodic Memories** sorted by semantic relevance.
3. The moment a memory snippet would push the total over the 800-token limit, the packing loop **stops immediately**. Unpacked memories are left out of the prompt.
4. Over time, a background job **decays** memories that haven't been accessed in 14 days, permanently deleting them if their confidence score drops below `0.1` to prevent database bloat.

---

## 🔍 4. Vector Search & Ranking

### How does the system rank episodic memories?
The system retrieves past memories using **Cosine Similarity/Distance** on vector embeddings:
1. When you send a message, the backend calls the Google Gemini Embedding API (`gemini-embedding-2`) to get a **768-dimensional vector** representing the conceptual meaning of your message.
2. The database computes the **Cosine Distance** between your message's vector and all your stored memories' vectors.
3. If two topics are semantically similar (e.g., *"green tea"* and *"matcha"*), they point in a similar direction in the vector space, yielding a very low distance score.
4. The database sorts these memories (closest match first) and returns the top results.

---

## 🧪 5. Evaluation Harness

### What is the "Evaluation & Simulation Harness"?
It is an automated testing pipeline built to verify the memory architecture. 
Instead of making you manually chat with the bot for days, clicking **"Run 5-Session Simulation"** automates a user journey of **5 sequential chat sessions** in a few seconds:
* **Session 1**: Sets a baseline profile (name, job, hobbies).
* **Session 2 & 3**: Introduces new details and **deliberate contradictions** (e.g., changing favorite programming languages or habits) to test if the backend correctly updates profile facts.
* **Session 4 & 5**: Simulates time passing to trigger memory retrieval and decay.
* **Score**: It calculates a final **Personalization Score (out of 10)** based on how successfully the system recalled facts and resolved profile conflicts.
