"""Voluntary read-only Robot Skill Hub filter/version-scope check, Python 3.10+.

At most nine bounded, anonymous GETs, no retries. DNT and telemetry opt-out are
mandatory. No packages, repository clone, token, file/outbox write, simulator,
robot, submission, claim or result publication is performed by this script.
PASS=exit 0; failed assertion=exit 1; transport/generation change=exit 2.
If downloaded with the supplied one-GET loader, the combined budget is ten GETs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HUB = "https://hub.superfastrobotics.com"
API = "https://api.superfastrobotics.com"
SKILL = "maniskill-panda-pick-cube"
SOURCE = "33967b9e3ead1f841eec57cc9f31d0d8b8cf0907"
LEGACY = "contrib-a5dd78ad4e1d4e3d"
CURRENT = "1.1.0"
FINDING_BASE_HUB = "f87522f2714f311776399e3d7e033eafdf2c7186"
ENVIRONMENT = {"runtime": "maniskill", "runtime_version": "3.0.0b22", "robot": "panda",
               "controller": "pd_joint_pos", "observation": "state", "os": "linux",
               "python": "3.10", "architecture": "x86_64"}
HEADERS = {"Accept": "application/json", "User-Agent": "robot-skill-hub-voluntary-readonly-check/1",
           "DNT": "1", "X-RSH-Telemetry": "off", "Cache-Control": "no-cache"}
MAX_REQUESTS = 9
MAX_BYTES = 2 * 1024 * 1024
INTERVAL = 0.65


class Inconclusive(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    checks, requests = {}, []
    generation = None
    findings_summary = None
    bytes_read = 0
    last_request = 0.0
    started = dt.datetime.now(dt.timezone.utc).isoformat()

    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def get(label, url, maximum=128 * 1024):
        nonlocal bytes_read, last_request
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"hub.superfastrobotics.com", "api.superfastrobotics.com"}:
            raise AssertionError("Unapproved URL")
        if parsed.username or parsed.password or parsed.fragment or len(requests) >= MAX_REQUESTS:
            raise AssertionError("Invalid URL or exhausted request budget")
        delay = INTERVAL - (time.monotonic() - last_request)
        if delay > 0:
            time.sleep(delay)
        last_request = time.monotonic()
        req = urllib.request.Request(url, headers=HEADERS, method="GET")
        entry = {"label": label, "url": url, "method": "GET", "DNT": "1", "X-RSH-Telemetry": "off"}
        requests.append(entry)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as response:
                entry["status"] = response.status
                raw = response.read(maximum + 1)
        except urllib.error.HTTPError as error:
            entry["status"] = error.code
            try:
                error.close()
            except (OSError, EOFError, http.client.HTTPException):
                pass  # Preserve the known HTTP status even if closing aborts.
            raise Inconclusive("HTTP " + str(error.code) + " at " + label + "; no automatic retry") from None
        except (OSError, EOFError, http.client.HTTPException) as error:
            raise Inconclusive(type(error).__name__ + " at " + label + "; no automatic retry") from None
        bytes_read += len(raw)
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if len(raw) > maximum or bytes_read > MAX_BYTES:
            raise AssertionError("Bounded response budget exceeded")
        return json.loads(raw)

    def api_url(path, parameters):
        return API + path + "?" + urllib.parse.urlencode({**parameters, "hub_commit": generation})

    def envelope(label, value, backend):
        if value.get("hub_commit") != generation:
            raise Inconclusive("Catalog generation changed at " + label)
        check(label + "_complete_data_only", value.get("coverage", {}).get("complete") is True
              and value.get("backend") == backend and value.get("interpretation") == "data_only"
              and value.get("execution_performed") is False)

    def findings(label, version=LEGACY, source=SOURCE, **environment):
        value = get(label, api_url("/v1/findings", {"skill_id": SKILL, "record_version": version,
            "source_commit": source, "limit": 2, "offset": 0, **environment}))
        envelope(label, value, "d1")
        check(label + "_bounded_complete_page", value.get("limit") == 2 and value.get("offset") == 0
              and value.get("next") is None and len(value.get("results", [])) == value.get("total"))
        return value

    try:
        version = get("publication_start", HUB + "/catalog/v1/version.json", 32 * 1024)
        generation = version.get("hub_commit")
        check("publication_has_full_commit", isinstance(generation, str) and re.fullmatch(r"[a-f0-9]{40}", generation) is not None)
        record_url = HUB + "/skills/" + SKILL + "/skill.json"
        record = get("inspect_declared_recipe", record_url + "?v=" + generation, 256 * 1024)
        record_sha256 = requests[-1]["sha256"]
        check("declared_recipe_exact_source_and_version", record.get("id") == SKILL
              and record.get("source", {}).get("commit") == SOURCE
              and record.get("maintenance", {}).get("record_version") == CURRENT)
        check("all_eight_fields_coexist_in_one_declared_combination", any(
            all(combo.get(key) == value for key, value in ENVIRONMENT.items())
            for combo in record.get("compatibility", []) if isinstance(combo, dict)))
        search = {"q": "PickCube-v1", "kind": "preparation_recipe", "limit": 3, "offset": 0}
        good = get("whole_combination_matches", api_url("/v1/search", {**search, **ENVIRONMENT}))
        envelope("whole_combination_matches", good, "d1_fts5")
        check("whole_combination_returns_exact_recipe_once", good.get("total") == 1 and good.get("next") is None
              and len(good.get("results", [])) == 1 and good["results"][0].get("id") == SKILL
              and good["results"][0].get("record_version") == CURRENT
              and good["results"][0].get("source_commit") == SOURCE
              and good["results"][0].get("record_url") == record_url
              and good["results"][0].get("record_sha256") == record_sha256
              and good["results"][0].get("kind") == "preparation_recipe"
              and good["results"][0].get("hub_prepare") is True
              and any(all(combo.get(k) == v for k, v in ENVIRONMENT.items())
                      for combo in good["results"][0].get("compatibility", [])))
        bad = get("undeclared_rgb_combination_excluded", api_url("/v1/search", {**search, **ENVIRONMENT, "observation": "rgb"}))
        envelope("undeclared_rgb_combination_excluded", bad, "d1_fts5")
        check("undeclared_combination_returns_zero", bad.get("total") == 0 and bad.get("results") == [] and bad.get("next") is None)
        legacy = findings("legacy_exact_version")
        rows = legacy.get("results", [])
        check("legacy_exact_version_has_two_distinct_findings", legacy.get("total") == 2
              and len({r.get("memory_id") for r in rows}) == 2)
        check("legacy_findings_keep_original_base_commit", generation != FINDING_BASE_HUB and all(
            r.get("skill_id") == SKILL and r.get("base") == {"hub_commit": FINDING_BASE_HUB,
                "record_version": LEGACY, "source_commit": SOURCE} for r in rows))
        check("legacy_finding_environment_and_trust_are_data_only", all(
            all(r.get("environment", {}).get(k) == v for k, v in ENVIRONMENT.items())
            and r.get("trust") == "contributor_reported" and r.get("interpretation") == "data_only"
            and r.get("curation") == "maintainer_merged" and r.get("hub_validation", {}).get("runtime") == "not_run"
            for r in rows))
        findings_summary = [{"memory_id": r["memory_id"], "base": r["base"], "trust": r["trust"]} for r in rows]
        for label, parameters in (("current_version_has_no_legacy_findings", {"version": CURRENT}),
                                  ("wrong_source_has_no_findings", {"source": "0" * 40}),
                                  ("windows_environment_has_no_legacy_findings", {"os": "windows"})):
            result = findings(label, **parameters)
            check(label, result.get("total") == 0 and result.get("results") == [])
        final_version = get("publication_end", HUB + "/catalog/v1/version.json", 32 * 1024)
        if final_version != version:
            raise Inconclusive("Publication changed during this check; no automatic retry")
        check("exactly_nine_bounded_GETs", len(requests) == 9)
        outcome, reason, code = "PASS", None, 0
    except AssertionError as error:
        outcome, reason, code = "FAIL", str(error), 1
    except (Inconclusive, ValueError, KeyError, TypeError) as error:
        outcome, reason, code = "INCONCLUSIVE", str(error), 2
    print(json.dumps({"schema_version": 1, "outcome": outcome, "reason": reason,
        "started_at": started, "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hub_commit": generation, "scope": "Read-only metadata/filter/version-scope check; no robot execution or adoption claim.",
        "python": sys.version.split()[0], "platform": sys.platform,
        "checks": checks, "legacy_findings": findings_summary, "requests": requests, "request_count": len(requests),
        "response_body_bytes": bytes_read, "requests_opt_out_of_measurement": True,
        "response_body_byte_scope": "Successfully returned bounded bodies; aborted internal reads may have unreported partial bytes.",
        "file_or_outbox_writes": False, "authentication_or_submission": False}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
