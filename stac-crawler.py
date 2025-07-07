import time
import json
import os
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

# Configuration
STAC_INDEX_CATALOGS_URL = "https://stacindex.org/api/catalogs"
OUTPUT_DIR = "stac_summaries_final"
PROFILE_OUTPUT_FILENAME = "catalog_profiles.json"
PLAN_OUTPUT_FILENAME = "crawl_plan.json"
FINAL_OUTPUT_FILENAME = "stac_knowledge_base.json"

# HTTP request settings
REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_HEADERS = {"User-Agent": "StacMasterCrawler/20.0"}

# Explicitly skip these catalogs
MANUAL_OVERRIDES = {
    "astraea-earth-ondemand": {"strategy": "Skip"},
    "bdc-cbers": {"strategy": "Skip"},
    "bdc-sentinel-2": {"strategy": "Skip"},
    "catalonia-monthly-sentinel2": {"strategy": "Skip"},
    "cbers": {"strategy": "Skip"},
    "disasters-charter-mapper-catalog": {"strategy": "Skip"},
    "kagis-katalog": {"strategy": "Skip"},
    "kyfromabove": {"strategy": "Skip"},
    "gistda-drought-index-in-thailand": {"strategy": "Skip"},
    "gistda-flood-disaster-in-thailand": {"strategy": "Skip"},
    "geoplatform-stac-catalog": {"strategy": "Skip"},
    "openaerialmap-example": {"strategy": "Skip"},
    "satellite-vu-public-static-stac": {"strategy": "Skip"},
    "skyserve-mission-data": {"strategy": "Skip"},
    "swiss-data-cube-p": {"strategy": "Skip"}
}

# Harvest strategies
DEFAULT_DYNAMIC_PARAMS = {"max_depth": 10}
DEFAULT_STATIC_PARAMS = {"STATIC_HARVEST_MAX_DEPTH": 3, "COLLECTION_HARD_LIMIT": 300}


def run_reconnaissance() -> Optional[List[Dict[str, Any]]]:
    """Stage 1: List and profile public STAC catalogs."""
    print("=" * 80)
    print("Stage 1: Starting reconnaissance crawl")
    print("=" * 80)

    try:
        resp = httpx.get(STAC_INDEX_CATALOGS_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
        resp.raise_for_status()
        catalogs = resp.json()
        public_catalogs = [cat for cat in catalogs if not cat.get("isPrivate", True) and cat.get("url")]
    except Exception as e:
        print(f"FATAL: Could not fetch catalog list: {e}")
        return None

    print(f"--> Found {len(public_catalogs)} public catalogs to profile.")
    profiles: List[Dict[str, Any]] = []

    # Check each catalog's accessibility
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
        for idx, cat in enumerate(public_catalogs, start=1):
            slug = cat.get("slug")
            title = cat.get("title", "N/A")
            url = cat.get("url")
            status = "OK"

            print(f"({idx}/{len(public_catalogs)}) Profiling: {title} ({slug})")

            if slug in MANUAL_OVERRIDES:
                status = "Skipped (Manual Override)"
                print("    -> Skipping due to manual override.")
            else:
                try:
                    client.get(url).raise_for_status()
                except Exception as e:
                    status = f"Failed: {type(e).__name__}"

            profiles.append({"slug": slug, "title": title, "url": url, "status": status})

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, PROFILE_OUTPUT_FILENAME), "w") as f:
        json.dump(profiles, f, indent=2)

    print(f"--> Profiles saved to {OUTPUT_DIR}/{PROFILE_OUTPUT_FILENAME}")
    return profiles


def generate_crawl_plan(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stage 2: Decide static or dynamic harvest strategy per catalog."""
    print("\n" + "="*80)
    print("Stage 2: Generating crawl plan")
    print("="*80)

    plan: Dict[str, Any] = {}
    for p in profiles:
        slug = p["slug"]
        status = p.get("status")
        url = p.get("url", "")

        if status != "OK":
            plan[slug] = {"strategy": "Skip"}
        elif url.endswith(('.json', 'f=json')):
            plan[slug] = {"strategy": "Static Harvest", **DEFAULT_STATIC_PARAMS}
        else:
            plan[slug] = {"strategy": "Dynamic Harvest", **DEFAULT_DYNAMIC_PARAMS}

    with open(os.path.join(OUTPUT_DIR, PLAN_OUTPUT_FILENAME), "w") as f:
        json.dump(plan, f, indent=2)

    print(f"--> Crawl plan saved to {OUTPUT_DIR}/{PLAN_OUTPUT_FILENAME}")
    return plan


async def harvest_static_catalog(start_url: str, params: Dict[str, Any]) -> Optional[tuple]:
    """Breadth-first static harvest of catalog up to depth and collection limits."""
    max_depth = params.get("STATIC_HARVEST_MAX_DEPTH", 3)
    hard_limit = params.get("COLLECTION_HARD_LIMIT", 300)

    print(f"    -> Static harvest (depth {max_depth}, limit {hard_limit})")

    collections = []
    crawl_notes = []
    to_fetch = {start_url}
    visited = set()
    depth = 0

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
        while to_fetch and len(collections) < hard_limit and depth < max_depth:
            tasks = [client.get(u) for u in to_fetch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            visited |= to_fetch
            next_level = set()

            for res in results:
                if isinstance(res, Exception):
                    continue
                try:
                    data = res.json()
                    t = data.get("type")
                    is_catalog = (isinstance(t, str) and t.lower() in ("catalog", "collection")) or data.get("stac_version")

                    if is_catalog:
                        collections.append(data)

                    for link in data.get("links", []):
                        if link.get("rel") in ("child", "collection"):
                            href = urljoin(str(res.url), link.get("href", ""))
                            if href and href not in visited:
                                next_level.add(href)
                except json.JSONDecodeError:
                    continue

            to_fetch = next_level
            depth += 1

    if len(collections) >= hard_limit:
        crawl_notes.append(f"Reached collection limit of {hard_limit}.")
    if depth >= max_depth:
        crawl_notes.append(f"Reached depth limit of {max_depth}.")

    return collections, crawl_notes


def _dynamic_worker(start_url: str, client: httpx.Client) -> List[Dict[str, Any]]:
    """Helper for dynamic harvesting of a single catalog endpoint."""
    unique = {}
    dynamic_limit = 0
    queue = [start_url]
    visited = {start_url}

    while queue:
        if dynamic_limit > 0 and len(unique) >= dynamic_limit:
            break

        url = queue.pop(0)
        try:
            res = client.get(url)
            res.raise_for_status()
            data = res.json()

            if "collections" in data and isinstance(data["collections"], list):
                if dynamic_limit == 0:
                    dynamic_limit = len(data["collections"])
                for item in data["collections"]:
                    if isinstance(item, dict) and "id" in item:
                        unique[item["id"]] = item

            if data.get("type") == "Collection" and "id" in data:
                unique[data["id"]] = data

            # enqueue sub-catalog links
            for link in data.get("links", []):
                if link.get("rel") in ["child", "data", "collection", "children"]:
                    href = urljoin(url, link.get("href", ""))
                    if href and href not in visited and not href.endswith('.json'):
                        visited.add(href)
                        queue.append(href)
        except Exception:
            continue

    return list(unique.values())


def harvest_dynamic_catalog(start_url: str, params: Dict[str, Any]) -> Optional[tuple]:
    """Dynamic harvest that handles federated catalogs and nested collections."""
    print("    -> Dynamic harvest")

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
        try:
            root = client.get(start_url); root.raise_for_status()
            data = root.json()
            collections = []
            crawl_notes = []

            child_links = [l for l in data.get("links", []) if l.get("rel") == "child"]
            has_master = any(l.get("href", "").endswith(('/collections', '/collections/')) for l in data.get("links", []))

            if child_links and not has_master:
                crawl_notes.append(f"Federated crawl with {len(child_links)} children.")
                for link in child_links:
                    href = urljoin(start_url, link.get('href', ''))
                    if href and not href.endswith('.json'):
                        print(f"       -> Crawling sub-catalog: {link.get('title', href)}")
                        collections.extend(_dynamic_worker(href, client))
            else:
                crawl_notes.append("Single endpoint crawl.")
                collections.extend(_dynamic_worker(start_url, client))

            return collections, crawl_notes
        except Exception as e:
            print(f"    -> FAILED: {type(e).__name__} on {start_url}")
            return None


def build_knowledge_base(crawl_plan: Dict[str, Any], profiles: List[Dict[str, Any]]) -> Optional[str]:
    """Stage 3: Execute harvesting per plan and compile results."""
    print("\n" + "="*80)
    print("Stage 3: Building knowledge base")
    print("="*80)

    entries = []
    success = 0
    failed = []

    to_process = [p for p in profiles if p.get('status') == 'OK']
    for idx, p in enumerate(to_process, start=1):
        slug, url, title = p['slug'], p['url'], p['title']
        plan = crawl_plan.get(slug, {})

        print(f"({idx}/{len(to_process)}) Processing: {title} ({slug})")
        result = None

        if plan.get('strategy') == 'Static Harvest':
            result = asyncio.run(harvest_static_catalog(url, plan))
        elif plan.get('strategy') == 'Dynamic Harvest':
            result = harvest_dynamic_catalog(url, plan)

        if not result:
            failed.append(f"{title} (processing error)")
            continue

        collections, notes = result
        if not collections:
            failed.append(f"{title} (no collections found)")
            continue

        print(f"    -> Discovered {len(collections)} unique collections")

        entry = {
            "slug": slug,
            "catalog_title": title,
            "catalog_url": url,
            "crawl_notes": notes,
            "collections": collections
        }
        entries.append(entry)
        success += 1

    # Save final knowledge base if any successes
    if entries:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = os.path.join(OUTPUT_DIR, FINAL_OUTPUT_FILENAME)
        with open(path, "w") as f:
            json.dump(entries, f, indent=2)
        print(f"--> Wrote {success} entries to {path}")
    else:
        print("No successful entries to write.")

    print("\nHarvesting summary:")
    print(f"Successful: {success}")
    print(f"Failed/Skipped: {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")

    return path if entries else None


def main():
    """Run full pipeline: reconnaissance, planning, harvesting."""
    start = time.time()

    profiles = run_reconnaissance()
    if not profiles:
        print("Pipeline halted: reconnaissance failed.")
        return

    plan = generate_crawl_plan(profiles)
    kb_path = build_knowledge_base(plan, profiles)
    if not kb_path:
        print("Pipeline halted: no knowledge base built.")
        return

    elapsed = (time.time() - start) / 60
    print(f"\nPipeline completed in {elapsed:.2f} minutes.")


if __name__ == "__main__":
    main()
