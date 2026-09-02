# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Reliable keyless web search for Chimera employee simulations."""

import base64
import ipaddress
import logging
import re
import socket
import threading
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from urllib3.util import connection

import config


# Use a child of the logger that run_task() attaches to each detailed task log.
_LOGGER = logging.getLogger("camel.web_search")
_IPV4_REQUEST_LOCK = threading.Lock()
_WEB_TOOL_STATE = threading.local()
_BING_SEARCH_URL = "https://www.bing.com/search"
_WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)
_CAPTCHA_MARKERS = (
    "captcha",
    "verify you are human",
    "verification required",
    "i'm not a robot",
    "i am not a robot",
    "cloudflare challenge",
    "checking your browser",
    "enable javascript and cookies to continue",
)
_QUERY_STOP_WORDS = {
    "a",
    "about",
    "and",
    "for",
    "from",
    "health",
    "how",
    "in",
    "latest",
    "new",
    "of",
    "on",
    "or",
    "recent",
    "the",
    "to",
    "with",
}
_QUERY_EXPANSIONS = {
    "ehr": ("electronic", "health", "record"),
    "fluview": ("influenza", "surveillance"),
}


def _search_error(message: str) -> List[Dict[str, Any]]:
    _LOGGER.warning("WEB_SEARCH_FAILED %s", message)
    return [{"error": message}]


def _meaningful_tokens(value: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in _QUERY_STOP_WORDS
    }


def _ordered_meaningful_tokens(value: str) -> List[str]:
    """Return meaningful query tokens once, preserving their original order."""

    ordered: List[str] = []
    seen: Set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if (
            len(token) < 3
            or token in _QUERY_STOP_WORDS
            or token in seen
        ):
            continue
        ordered.append(token)
        seen.add(token)
    return ordered


def _search_query_variants(query: str) -> List[str]:
    """Build bounded reorderings for Bing installations that drop later terms.

    The Bing HTML endpoint currently reachable from the container sometimes
    behaves as if only the leading term mattered.  Retrying every permutation
    would create excessive traffic, so try the original query followed by a
    few deterministic variants led by a long term or a short acronym.
    """

    tokens = _ordered_meaningful_tokens(query)
    variants = [query]
    expanded_tokens: List[str] = []
    for token in tokens:
        expanded_tokens.extend(_QUERY_EXPANSIONS.get(token, (token,)))
    expanded_query = " ".join(expanded_tokens)
    if expanded_query and expanded_query != query.lower():
        variants.append(expanded_query)
    if len(tokens) < 2 or len(variants) >= config.web_search_max_attempts:
        return variants[: config.web_search_max_attempts]

    leading = tokens[0]
    remaining = tokens[1:]
    priorities: List[str] = []

    longest = max(
        remaining,
        key=lambda token: (len(token), -tokens.index(token)),
    )
    priorities.append(longest)

    for token in remaining:
        if len(token) <= 4 and token not in priorities:
            priorities.append(token)

    for token in sorted(
        remaining,
        key=lambda item: (-len(item), tokens.index(item)),
    ):
        if token not in priorities:
            priorities.append(token)

    for first_token in priorities:
        reordered = [first_token, leading]
        reordered.extend(
            token
            for token in remaining
            if token != first_token
        )
        variant = " ".join(reordered)
        if variant not in variants:
            variants.append(variant)
        if len(variants) >= config.web_search_max_attempts:
            break
    return variants[: config.web_search_max_attempts]


def _required_query_token_matches(query_tokens: Set[str]) -> int:
    """Require more than a single generic word for multi-term queries."""

    return 2 if len(query_tokens) >= 3 else 1


def _authority_score(url: str) -> int:
    """Lightly prefer public-health, government and academic sources."""

    hostname = (urlparse(url).hostname or "").lower()
    if hostname.endswith((".gov", ".gov.uk", ".gc.ca", ".int")):
        return 2
    if hostname.endswith((".edu", ".ac.uk")):
        return 1
    return 0


def _search_wikipedia(
    query: str,
    query_tokens: Set[str],
    required_matches: int,
    result_limit: int,
) -> tuple[List[Dict[str, Any]], str]:
    """Return bounded Wikipedia results when Bing HTML is temporarily poor."""

    try:
        response = _request_ipv4(
            _WIKIPEDIA_SEARCH_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": min(max(result_limit * 2, 5), 10),
                "format": "json",
                "utf8": 1,
            },
            headers={
                "User-Agent": "Chimera-Medical/1.0 (bounded web search)",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=(
                config.web_search_connect_timeout,
                config.web_search_timeout,
            ),
        )
    except requests.RequestException as exc:
        return [], f"Wikipedia fallback request failed: {exc}"

    try:
        if response.status_code != 200:
            return [], f"Wikipedia fallback returned HTTP {response.status_code}."
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            return [], f"Wikipedia fallback returned invalid JSON: {exc}"
    finally:
        response.close()

    raw_results = payload.get("query", {}).get("search", [])
    if not isinstance(raw_results, list):
        return [], "Wikipedia fallback returned an invalid result structure."

    results: List[Dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        snippet = item.get("snippet", "")
        if not isinstance(title, str) or not title:
            continue
        description = BeautifulSoup(str(snippet), "html.parser").get_text(
            " ", strip=True
        )
        article_path = quote(title.replace(" ", "_"), safe="()_-")
        public_url = f"https://en.wikipedia.org/wiki/{article_path}"
        result_tokens = _meaningful_tokens(
            f"{title} {description} {public_url}"
        )
        match_count = len(query_tokens.intersection(result_tokens))
        if query_tokens and match_count < required_matches:
            continue
        results.append(
            {
                "result_id": 0,
                "title": title,
                "description": description,
                "url": public_url,
                "_match_count": match_count,
                "_authority_score": _authority_score(public_url),
            }
        )
        if len(results) >= result_limit:
            break
    return results, ""


def _unwrap_bing_url(url: str) -> str:
    """Return the public destination embedded in a Bing ``/ck/a`` URL."""

    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"bing.com", "www.bing.com"}:
        return url
    encoded_values = parse_qs(parsed.query).get("u", [])
    if not encoded_values:
        return url
    encoded = encoded_values[0]
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return url
    return decoded if urlparse(decoded).scheme in {"http", "https"} else url


def _validate_public_url(url: str) -> Optional[str]:
    """Validate a web URL and reject loopback/private/link-local targets."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "Only public http:// or https:// URLs are supported."
    if parsed.username or parsed.password:
        return "URLs containing embedded credentials are not supported."

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        return f"The hostname could not be resolved: {exc}."

    for address in {item[4][0] for item in addresses}:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            return "Private, loopback, reserved and link-local targets are blocked."
    return None


def _request_ipv4(url: str, **kwargs: Any) -> requests.Response:
    """Perform one requests call while forcing IPv4 resolution."""

    with _IPV4_REQUEST_LOCK:
        original_allowed_family = connection.allowed_gai_family
        connection.allowed_gai_family = lambda: socket.AF_INET
        try:
            return requests.get(url, **kwargs)
        finally:
            connection.allowed_gai_family = original_allowed_family


def search_web(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search the public web with Bing HTML and return structured results.

    This backend does not require an API key. It deliberately uses IPv4 because
    the Docker host's current IPv6 route can leave Google/Bing connections in
    SYN-SENT for minutes. Network and parsing failures are returned as a normal
    tool result so they cannot terminate an employee worker or create an
    unbounded tool loop.

    Args:
        query: Search terms to look up on the public web.
        max_results: Number of results to return, from 1 through 10.

    Returns:
        A list of result objects containing result_id, title, description and
        url. On failure, the list contains one object with an error field.
    """
    if not isinstance(query, str) or not query.strip():
        return _search_error("The search query must be a non-empty string.")
    query = query.strip()
    if len(query) > config.web_query_max_chars:
        return _search_error(
            f"The search query exceeds {config.web_query_max_chars} characters."
        )

    try:
        result_limit = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        return _search_error("max_results must be an integer from 1 through 10.")

    results: List[Dict[str, Any]] = []
    original_query_tokens = _meaningful_tokens(query)
    query_tokens = original_query_tokens
    required_matches = _required_query_token_matches(original_query_tokens)
    result_urls: Set[str] = set()
    attempts = 0
    last_error = ""
    fallback_used = False

    for search_query in _search_query_variants(query):
        attempts += 1
        try:
            response = _request_ipv4(
                _BING_SEARCH_URL,
                params={"q": search_query},
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=(
                    config.web_search_connect_timeout,
                    config.web_search_timeout,
                ),
            )
        except requests.RequestException as exc:
            last_error = f"Bing search request failed: {exc}"
            continue

        try:
            if response.status_code != 200:
                last_error = f"Bing search returned HTTP {response.status_code}."
                continue
            soup = BeautifulSoup(response.text, "html.parser")
        finally:
            response.close()

        for row in soup.select("li.b_algo"):
            if not isinstance(row, Tag):
                continue
            link = row.select_one("h2 a")
            if not isinstance(link, Tag):
                continue

            url = link.get("href")
            title = link.get_text(" ", strip=True)
            if not isinstance(url, str) or not url or not title:
                continue

            snippet_element = row.select_one(".b_caption p, p")
            description = (
                snippet_element.get_text(" ", strip=True)
                if isinstance(snippet_element, Tag)
                else ""
            )
            public_url = _unwrap_bing_url(url)
            result_tokens = _meaningful_tokens(
                f"{title} {description} {public_url}"
            )
            match_count = len(query_tokens.intersection(result_tokens))
            if query_tokens and match_count < required_matches:
                continue
            if public_url in result_urls:
                continue

            result_urls.add(public_url)
            results.append(
                {
                    "result_id": 0,
                    "title": title,
                    "description": description,
                    "url": public_url,
                    "_match_count": match_count,
                    "_authority_score": _authority_score(public_url),
                }
            )

        if len(results) >= result_limit:
            break

    if not results:
        fallback_results, fallback_error = _search_wikipedia(
            query,
            query_tokens,
            required_matches,
            result_limit,
        )
        if fallback_results:
            fallback_used = True
            for result in fallback_results:
                if result["url"] in result_urls:
                    continue
                result_urls.add(result["url"])
                results.append(result)
        elif fallback_error:
            last_error = (
                f"{last_error} {fallback_error}".strip()
            )

    if not results:
        return _search_error(last_error or (
            "Bing returned no sufficiently relevant search results after "
            f"{attempts} bounded attempt(s)."
        ))

    results.sort(
        key=lambda item: (
            item["_match_count"],
            item["_authority_score"],
        ),
        reverse=True,
    )
    results = results[:result_limit]
    for result_id, result in enumerate(results, start=1):
        result["result_id"] = result_id
        result.pop("_match_count", None)
        result.pop("_authority_score", None)

    allowed_urls = getattr(_WEB_TOOL_STATE, "allowed_urls", set())
    allowed_urls.update(result["url"] for result in results)
    _WEB_TOOL_STATE.allowed_urls = allowed_urls
    _WEB_TOOL_STATE.failed_fetches = 0

    if config.log_model_content:
        _LOGGER.info(
            "WEB_SEARCH_COMPLETE query=%r result_count=%s attempts=%s "
            "wikipedia_fallback=%s",
            query,
            len(results),
            attempts,
            fallback_used,
        )
    else:
        _LOGGER.info(
            "WEB_SEARCH_COMPLETE result_count=%s attempts=%s "
            "wikipedia_fallback=%s",
            len(results),
            attempts,
            fallback_used,
        )
    return results


def _fetch_url_from_public_web(url: str) -> Dict[str, Any]:
    """Fetch and extract a bounded amount of text without launching Chromium.

    Redirect targets are validated individually to prevent the model from
    reaching Docker/host control services.  CAPTCHA/challenge pages are
    returned as a normal blocked result and are never retried.
    """

    if not isinstance(url, str) or not url.strip():
        return {"status": "error", "error": "url must be a non-empty string."}

    current_url = url.strip()
    for redirect_index in range(config.web_fetch_max_redirects + 1):
        validation_error = _validate_public_url(current_url)
        if validation_error:
            return {"status": "error", "url": current_url, "error": validation_error}

        try:
            response = _request_ipv4(
                current_url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.1",
                },
                timeout=(
                    config.web_search_connect_timeout,
                    config.web_search_timeout,
                ),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            return {
                "status": "error",
                "url": current_url,
                "error": f"Web fetch failed: {exc}",
            }

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                return {
                    "status": "error",
                    "url": current_url,
                    "error": "Redirect response did not contain a Location header.",
                }
            if redirect_index >= config.web_fetch_max_redirects:
                return {
                    "status": "error",
                    "url": current_url,
                    "error": "Too many redirects.",
                }
            current_url = urljoin(current_url, location)
            continue

        if not 200 <= response.status_code < 300:
            status_code = response.status_code
            response.close()
            return {
                "status": "error",
                "url": current_url,
                "error": f"Web fetch returned HTTP {status_code}.",
            }

        content_type = response.headers.get("Content-Type", "").lower()
        if not any(
            allowed in content_type
            for allowed in ("text/", "application/json", "application/xhtml+xml")
        ):
            response.close()
            return {
                "status": "error",
                "url": current_url,
                "error": f"Unsupported content type: {content_type or 'unknown'}.",
            }

        chunks: List[bytes] = []
        bytes_read = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                remaining = config.web_fetch_max_bytes - bytes_read
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                bytes_read += min(len(chunk), remaining)
        finally:
            response.close()

        encoding = response.encoding or "utf-8"
        try:
            raw_text = b"".join(chunks).decode(encoding, errors="replace")
        except LookupError:
            raw_text = b"".join(chunks).decode("utf-8", errors="replace")
        title = ""
        if "html" in content_type or "xhtml" in content_type:
            soup = BeautifulSoup(raw_text, "html.parser")
            if soup.title:
                title = soup.title.get_text(" ", strip=True)
            for unwanted in soup(["script", "style", "noscript", "svg"]):
                unwanted.decompose()
            extracted = soup.get_text(" ", strip=True)
        else:
            extracted = raw_text.strip()

        challenge_text = f"{title} {extracted[:4000]}".lower()
        if any(marker in challenge_text for marker in _CAPTCHA_MARKERS):
            _LOGGER.warning("WEB_FETCH_BLOCKED reason=captcha url=%s", current_url)
            return {
                "status": "blocked",
                "reason": "captcha",
                "url": current_url,
                "title": title,
            }

        text_value = extracted[: config.web_fetch_max_chars]
        if not text_value:
            return {
                "status": "error",
                "url": current_url,
                "error": "The page contained no readable text.",
            }
        _LOGGER.info(
            "WEB_FETCH_COMPLETE url=%s chars=%s", current_url, len(text_value)
        )
        return {
            "status": "success",
            "url": current_url,
            "title": title,
            "text": text_value,
            "truncated": len(extracted) > len(text_value),
        }

    return {"status": "error", "url": current_url, "error": "Fetch failed."}


def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch only a URL discovered by this task's bounded search flow."""

    if not isinstance(url, str) or not url.strip():
        return {"status": "error", "error": "url must be a non-empty string."}
    requested_url = url.strip()
    validation_error = _validate_public_url(requested_url)
    if validation_error:
        return {
            "status": "error",
            "url": requested_url,
            "error": validation_error,
        }
    if config.web_fetch_require_search_result:
        allowed_urls = getattr(_WEB_TOOL_STATE, "allowed_urls", set())
        if requested_url not in allowed_urls:
            return {
                "status": "error",
                "url": requested_url,
                "error": (
                    "URL was not returned by a successful search_web call in "
                    "this task. Search first and copy an exact result URL."
                ),
            }
    failed_fetches = getattr(_WEB_TOOL_STATE, "failed_fetches", 0)
    if failed_fetches >= config.web_fetch_max_failures:
        return {
            "status": "blocked",
            "reason": "fetch_failure_limit",
            "error": (
                "The bounded fetch failure limit was reached; continue with "
                "available search snippets and label unverified claims."
            ),
        }
    result = _fetch_url_from_public_web(requested_url)
    if result.get("status") == "success":
        _WEB_TOOL_STATE.failed_fetches = 0
    else:
        _WEB_TOOL_STATE.failed_fetches = failed_fetches + 1
    return result
