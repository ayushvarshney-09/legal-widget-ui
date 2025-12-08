from flask import Flask, request, jsonify, send_file
import os
import requests

app = Flask(__name__)

# -----------------------------
# CONFIG – EDIT THESE
# -----------------------------

PROJECT_ID = os.environ.get("PROJECT_ID", "your-project-id")
LOCATION = os.environ.get("LOCATION", "us-central1")

# Agent Engine deep agent endpoint (from Agent Engine UI → service details)
# Example:
# https://us-central1-agents.googleapis.com/v1/projects/123456789012/locations/us-central1/reasoningEngines/deep-search-173:sessions
DEEP_AGENT_ENDPOINT = os.environ.get(
    "DEEP_AGENT_ENDPOINT",
    "https://us-central1-agents.googleapis.com/v1/projects/PROJECT_NUMBER/"
    "locations/us-central1/reasoningEngines/ENGINE_ID:sessions"
)

# Vertex AI Search endpoint for your data store
# Example:
# https://discoveryengine.googleapis.com/v1/projects/your-project-id/locations/global/collections/default_collection/dataStores/DATASTORE_ID/servingConfigs/default_search:search
VERTEX_SEARCH_URL = os.environ.get(
    "VERTEX_SEARCH_URL",
    "https://discoveryengine.googleapis.com/v1/"
    "projects/your-project-id/locations/global/collections/default_collection/"
    "dataStores/DATASTORE_ID/servingConfigs/default_search:search"
)

# -----------------------------
# ROUTING RULE
# -----------------------------

def is_legal_docs_question(q: str) -> bool:
    """Very simple heuristic: mention of contracts/docs ⇒ Vertex AI Search."""
    keywords = ["contract", "clause", "nda", "agreement", "policy", "legal", "document"]
    q_low = q.lower()
    return any(k in q_low for k in keywords)

# -----------------------------
# AUTH TOKEN (Cloud Run SA or local dev)
# -----------------------------

def get_access_token() -> str:
    """Get OAuth token using Cloud Run default service account or gcloud in local dev."""
    if os.environ.get("LOCAL_DEV") == "1":
        # Local development: needs gcloud installed and logged in
        return os.popen("gcloud auth print-access-token").read().strip()

    resp = requests.get(
        "http://metadata/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# -----------------------------
# CALL DEEP AGENT (Agent Engine)
# -----------------------------

def call_deep_agent(query: str) -> str:
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": {"text": query},
        "session": {},  # simple stateless session
    }
    resp = requests.post(DEEP_AGENT_ENDPOINT, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Adjust this path to match your Agent Engine response
    return data.get("output", {}).get("text", "No answer from deep agent.")

# -----------------------------
# CALL VERTEX AI SEARCH
# -----------------------------

def call_vertex_search(query: str) -> str:
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "pageSize": 3,
    }
    resp = requests.post(VERTEX_SEARCH_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "No matching documents were found in the legal index."
    first = results[0]
    # Depending on your Search config this may be 'snippet' or in document fields
    snippet = first.get("snippet", "")
    return snippet or "Found documents, but no snippet was available."

# -----------------------------
# ROUTES
# -----------------------------

@app.route("/")
def root():
    # existing behavior: serve your HTML page with the widget / UI
    return send_file("index.html")

@app.post("/chat")
def chat():
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"answer": "Empty query."}), 400

    try:
        if is_legal_docs_question(query):
            answer = call_vertex_search(query)
            source = "vertex_search"
        else:
            answer = call_deep_agent(query)
            source = "deep_agent"
        return jsonify({"answer": answer, "source": source})
    except Exception as e:
        return jsonify({"answer": f"Error: {e}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
