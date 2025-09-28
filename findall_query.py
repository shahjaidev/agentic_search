import json
import os
import time

import requests

# Configuration — replace with your own API key
API_KEY = os.getenv("PARALLEL_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://api.parallel.ai"
INGEST_ENDPOINT = f"{BASE_URL}/v1beta/findall/ingest"
RUNS_ENDPOINT = f"{BASE_URL}/v1beta/findall/runs"

def run_findall_query(query: str, result_limit: int = 50, poll_interval: float = 15.0):
    """
    Send a natural language query to the Parallel FindAll API and wait for results.

    Args:
        query: The natural language query (e.g. “Find all US based AI companies that raised Series A funding in the past 2 years and keep columns for all relevant info like name, product description, website, founder names, current team size estimate, location, total funding raised, and funding round details”).
        result_limit: Maximum number of entities to return in the run.
        poll_interval: Seconds to wait between polling the run status.

    Returns:
        The final JSON response containing “results” and metadata.
    """
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }

    # Step 1: Ingest — convert the natural language query into a structured spec
    ingest_payload = {"query": query}
    ingest_resp = requests.post(INGEST_ENDPOINT, headers=headers, json=ingest_payload)
    ingest_resp.raise_for_status()
    findall_spec = ingest_resp.json()
    # Optionally inspect findall_spec["columns"], spec name, etc.
    print(f"★ Ingested spec: name={findall_spec.get('name')}, #columns={len(findall_spec.get('columns', []))}")

    # Step 2: Run — start the FindAll run
    run_payload = {
        "findall_spec": findall_spec,
        "processor": "base",
        "result_limit": result_limit
    }
    run_resp = requests.post(RUNS_ENDPOINT, headers=headers, json=run_payload)
    run_resp.raise_for_status()
    run_info = run_resp.json()
    findall_id = run_info["findall_id"]
    print(f"★ Started FindAll run with id: {findall_id}")

    output_path = f"file_run_{findall_id}.jsonl"
    print(f"★ Streaming results to {output_path}")

    def _result_key(result_item):
        for key_name in ("entity_id", "id", "uuid"):
            if result_item.get(key_name) is not None:
                return f"{key_name}:{result_item[key_name]}"
        return json.dumps(result_item, sort_keys=True)

    # Step 3: Poll for results until complete
    status_endpoint = f"{RUNS_ENDPOINT}/{findall_id}"
    seen_results = set()
    results = []
    with open(output_path, "w", encoding="utf-8") as output_file:
        while True:
            poll_resp = requests.get(status_endpoint, headers=headers)
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            # You’ll typically see fields like “status”, “is_active”, “are_enrichments_active”, “results”
            status = poll_data.get("status")
            results = poll_data.get("results", [])
            print(f"Status: {status} — {len(results)} results so far")

            new_lines = 0
            for result_item in results:
                key = _result_key(result_item)
                if key in seen_results:
                    continue
                seen_results.add(key)
                output_file.write(json.dumps(result_item))
                output_file.write("\n")
                output_file.flush()
                new_lines += 1
            if new_lines:
                print(f"★ Wrote {new_lines} new results to {output_path}")

            # According to docs, the run is done when both is_active and are_enrichments_active are false
            if not poll_data.get("is_active", False) and not poll_data.get("are_enrichments_active", False):
                break

            time.sleep(poll_interval)

    print(f"★ Completed run. Total results: {len(results)}")
    return poll_data

if __name__ == "__main__":
    # Example usage
    query = "Find all AI companies that raised Series A funding in 2024"
    result = run_findall_query(query, result_limit=10)
    # Print a few results
    for ent in result.get("results", [])[:5]:
        print(f" • {ent.get('name')} (score={ent.get('score')})")
