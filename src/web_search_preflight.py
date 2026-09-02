# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Fail-fast web-search readiness check for host capture runners."""

import config
from web_search import fetch_url, search_web


def main() -> None:
    if config.web_mode == "llm_only":
        print("Web preflight skipped: CHIMERA_WEB_MODE=llm_only.")
        return

    checks = (
        (
            "WHO seasonal influenza surveillance guidance",
            {"influenza", "seasonal"},
        ),
        ("FluView CDC weekly report", {"influenza", "cdc"}),
    )
    fetch_candidates = []
    for query, required_terms in checks:
        results = search_web(query, max_results=3)
        if not results:
            raise RuntimeError(f"Web search returned no results for {query!r}.")
        if results[0].get("error"):
            raise RuntimeError(results[0]["error"])

        relevant_results = []
        for result in results:
            searchable = " ".join(
                str(result.get(field, ""))
                for field in ("title", "description", "url")
            ).lower()
            if all(term in searchable for term in required_terms):
                relevant_results.append(result)
        if not relevant_results:
            raise RuntimeError(
                f"Web search results for {query!r} failed semantic relevance."
            )
        fetch_candidates.extend(relevant_results)

    fetch_errors = []
    for result in fetch_candidates:
        fetched = fetch_url(result["url"])
        if fetched.get("status") == "success" and fetched.get("text"):
            break
        fetch_errors.append(fetched.get("error", fetched.get("status")))
    else:
        raise RuntimeError(
            "No semantically relevant search result could be fetched: "
            + "; ".join(str(error) for error in fetch_errors)
        )

    print("Web search/fetch preflight passed.")


if __name__ == "__main__":
    main()
