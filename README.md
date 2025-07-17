# STAC Crawler

A Python-based pipeline to discover, profile, and harvest geospatial collections from public [STAC](https://stacindex.org) catalogs.

Exploratory project built in a weekend. Initially began as an MCP server based project, but I quickly realized that without additional context, an LLM cannot make informed decisions on
which datasets to suggest to the user for a geospatial oriented task/prompt. Instead of building for specific stacs (i.e. planetary computer, nasa, copernicus, etc...)
I wanted to utilize the stac index api catalog (https://stacindex.org/api/catalogs) and subsequentially realized how varied the structures of stacs from different sources can be.
The script sucessfully navigates through ~67 public catalogs in the index extracting descriptions and keywords. Some stacs have been purposely excluded for numerous reasons, such as, 
connection issues, poor formatting, or simply size. The output is a large (350k KB) json that could ideally be accessed by an LLM and provide context for decision making.

Ideally I would still like to turn this into an MCP server, possibly once nailing down and finalizing the scripts ability to successfully and fully navigate through stacs in a reasonable time
and without being overly complicated or micro-engineered for specific issues.

Future plans - sentence transformer or yake to summarize the json ouput

---

## Overview

The STAC Crawler is a three-stage pipeline that:

1. **Profiles** all public STAC catalogs listed in the STAC Index.
2. **Generates** a crawl plan to decide between static or dynamic harvesting per catalog.
3. **Harvests** catalog contents and compiles a unified knowledge base of discovered collections.

It saves intermediate JSON artifacts for auditing and downstream processing.

---

## Features

* **Automated discovery** of public STAC catalogs via the STAC Index API.
* **Flexible harvesting** strategies:
  * **Static Harvest** performs a breadth-first traversal, obeying depth and collection limits. Mostly for .json catalogs with no /search enabled. Steps through catalog.json links
  * **Dynamic Harvest** handles federated catalogs by following child links recursively through /search. Opens a single collections link and scrapes from there.
* **Manual overrides** to skip known problematic catalogs.
* **Progress logging** at each stage.
* **Final knowledge base** in JSON format for easy consumption.

---

## Requirements

* **Python** 3.8 or later
* **pip** (for installing dependencies)

## Configuration

All settings live at the top of `stac_crawler.py`:

| Variable                  | Description                                                                     | Default                                                         |
| ------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `STAC_INDEX_CATALOGS_URL` | STAC Index API endpoint for catalog listing                                     | `https://stacindex.org/api/catalogs`                            |
| `OUTPUT_DIR`              | Directory to save JSON outputs                                                  | `stac_summaries_final`                                          |
| `PROFILE_OUTPUT_FILENAME` | Filename for catalog profiles                                                   | `catalog_profiles.json`                                         |
| `PLAN_OUTPUT_FILENAME`    | Filename for generated crawl plan                                               | `crawl_plan.json`                                               |
| `FINAL_OUTPUT_FILENAME`   | Filename for the final knowledge base                                           | `stac_knowledge_base.json`                                      |
| `REQUEST_TIMEOUT_SECONDS` | HTTP request timeout (seconds)                                                  | `30.0`                                                          |
| `DEFAULT_HEADERS`         | HTTP headers (including `User-Agent`)                                           | `{"User-Agent": "StacMasterCrawler/20.0"}`                      |
| `MANUAL_OVERRIDES`        | Dict of catalog slugs to skip (set strategy to `Skip`)                          | See script for default entries                                  |
| `DEFAULT_DYNAMIC_PARAMS`  | Params for dynamic harvest (`max_depth`)                                        | `{"max_depth": 10}`                                             |
| `DEFAULT_STATIC_PARAMS`   | Params for static harvest (`STATIC_HARVEST_MAX_DEPTH`, `COLLECTION_HARD_LIMIT`) | `{"STATIC_HARVEST_MAX_DEPTH": 3, "COLLECTION_HARD_LIMIT": 300}` |

---

## Usage

Run the full pipeline end-to-end:

```bash
python stac_crawler.py
```

This will execute:

1. **`run_reconnaissance()`** — Profiles public catalogs
2. **`generate_crawl_plan()`** — Determines static vs dynamic strategy
3. **`build_knowledge_base()`** — Harvests catalogs and writes the final JSON

Intermediate and final outputs are placed under `<OUTPUT_DIR>`.

---

## Pipeline Stages

### Stage 1: Reconnaissance

* Fetches the list of catalogs from `STAC_INDEX_CATALOGS_URL`.
* Filters out private or malformed entries.
* Profiles each catalog by attempting an HTTP GET.
* Marks status as `OK`, `Skipped (Manual Override)`, or `Failed: <Error>`.
* Saves `catalog_profiles.json` with `{slug, title, url, status}` entries.

### Stage 2: Crawl Plan

* Reads the profiles and, for each `OK` catalog:

  * Uses **Static Harvest** if the URL ends in `.json` or has `f=json`.
  * Uses **Dynamic Harvest** otherwise.
  * Skips any non-OK entries.
* Saves `crawl_plan.json` mapping catalog slugs to harvest strategies and parameters.

### Stage 3: Harvest & Knowledge Base

* Iterates over the crawl plan:

  * **Static Harvest** performs a breadth-first traversal, obeying depth and collection limits. Mostly for .json catalogs with no /search enabled
  * **Dynamic Harvest** handles federated catalogs by following child links recursively through /search.
* Collects all unique collection objects.
* Logs crawl notes (e.g., depth/limit reached, federated child count).
* Compiles a final list of `{slug, catalog_title, catalog_url, crawl_notes, collections}` into `stac_knowledge_base.json`.

---

## Output Files

All outputs are written to the `OUTPUT_DIR` (default: `stac_summaries_final`):

* **`catalog_profiles.json`** — Profile results per catalog
* **`crawl_plan.json`** — Harvest strategy and parameters per catalog
* **`stac_knowledge_base.json`** — Aggregated knowledge base of discovered collections WARNING: THIS IS A HUGE JSON - 350,000 KB

---

## Customization & Troubleshooting

* **Adjust timeouts** by modifying `REQUEST_TIMEOUT_SECONDS`.
* **Override skips** by editing `MANUAL_OVERRIDES` with additional slugs.
* **Change harvest depth/limits** via `DEFAULT_DYNAMIC_PARAMS` and `DEFAULT_STATIC_PARAMS`.
* **Enable detailed logging**: Replace `print()` calls with Python’s `logging` module at `DEBUG` level.
* **Error handling**: The script continues past individual failures; review console output for errors.

---

## License

This project is open source and available under the MIT License.
