#!/usr/bin/env python3
"""Robot Skill Hub standalone entry point. Requires Python 3.10+, no extra packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.parse

from rshlib import acquisition, contributions, intake, memories, remote_catalog, setup
from rshlib.core import RshError, find, inspect, load_catalog, lookup_preparation, read_json, require_url
from rshlib.discovery import load_discovery, pinned_project_catalog
from rshlib.prepare import prepare


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RshError("invalid_arguments", message, next_action="read_command_help")


def environment_options(parser):
    parser.add_argument("--environment", help="JSON object describing the current project environment")
    for option in ("runtime", "runtime-version", "robot", "controller", "observation", "os"):
        parser.add_argument("--" + option)
    parser.add_argument("--python-version", dest="python", help="Project Python version, for example 3.10.11")
    parser.add_argument("--architecture", help="Project architecture, for example x86_64")


def build_parser():
    parser = Parser(description=__doc__)
    parser.add_argument("--catalog", help="Explicit catalog file or HTTPS index, overriding default discovery")
    parser.add_argument("--offline", action="store_true", help="Use cached/bundled indexes without network discovery or memory delivery")
    parser.add_argument("--refresh", action="store_true", help="Refresh the public discovery index within a short timeout")
    parser.add_argument("--json", action="store_true", help="JSON only on stdout, no prompts (accepted anywhere)")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    configure = sub.add_parser("setup", help="Configure explicit project memory scope without prompts or network access")
    configure.add_argument("--project", required=True)
    mode = configure.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local-only", action="store_true", help="Preserve findings locally without public memory permission")
    mode.add_argument("--allow-public-memory", action="store_true", help="Record public scope already authorized by the user")
    configure.add_argument("--skill", action="append", default=[], help="Explicit allowed skill ID; repeat for each authorized skill")
    configure.add_argument("--kind", action="append", default=[], choices=sorted(memories.KINDS), help="Explicit allowed finding kind; repeat as needed")
    check = sub.add_parser("setup-check", help="Read project scope and local credentials; network access requires --check-api")
    check.add_argument("--project", required=True)
    check.add_argument("--check-api", action="store_true", help="Perform one authenticated, read-only API session request")
    check.add_argument("--api-url")
    search = sub.add_parser("find", help="Find at most three candidate recipes without running their code")
    search.add_argument("query")
    search.add_argument("--query-mode", choices=("all_terms", "task"), default="all_terms",
                        help="Opt in to bounded English task ranking; default requires every query term")
    search.add_argument("--limit", type=int, default=3, choices=(1, 2, 3))
    search.add_argument("--offset", type=int, default=0, help="Read a later bounded search page (0..1000000)")
    search.add_argument("--hub-commit", help="Keep search pagination on the exact Hub generation returned by the previous page")
    environment_options(search)
    detail = sub.add_parser("inspect", help="Read source, requirements and verification evidence")
    detail.add_argument("skill_id")
    environment_options(detail)
    fetch = sub.add_parser("fetch-source", help="Save one checksum-verified source-reference file as inert data; never install or run it")
    fetch.add_argument("skill_id")
    fetch.add_argument("--project", required=True)
    fetch.add_argument("--plan", action="store_true", help="Validate metadata only; no upstream request or project writes")
    fetch.add_argument("--expected-source-revision", help="Require the exact revision returned by inspect")
    fetch.add_argument("--expected-source-sha256", help="Require the exact source-file digest returned by inspect")
    prep = sub.add_parser("prepare", help="Download pinned source and create an isolated environment; never run task")
    prep.add_argument("skill_id")
    prep.add_argument("--project", required=True)
    prep.add_argument("--plan", action="store_true", help="Read metadata and return a plan; no source download, install or project writes")
    prep.add_argument("--download-only", action="store_true", help="Download verified sources for a documented target; no environment or install")
    prep.add_argument("--source-archive", help="Use an already downloaded archive after checking the catalog SHA-256")
    prep.add_argument("--install-deps", action="store_true", help="Explicitly permit the printed dependency installation commands")
    prep.add_argument("--expected-source-commit", help="Require the exact source selected by find/inspect")
    prep.add_argument("--expected-record-version", help="Require the exact recipe version selected by find/inspect")
    environment_options(prep)
    bundle = sub.add_parser("bundle", aliases=["create-patch-bundle"], help="Preserve an explicit minimal patch and metadata locally")
    bundle.add_argument("skill_id")
    bundle.add_argument("--patch", required=True)
    bundle.add_argument("--metadata", required=True)
    bundle.add_argument("--output", required=True)
    bundle.add_argument("--project", required=True)
    bundle.add_argument("--policy")
    bundle.add_argument("--hub-commit", help="Exact original hub commit if absent from the snapshot/project lock")
    send = sub.add_parser("submit", help="Submit a permitted public patch through the hub API")
    send.add_argument("bundle")
    send.add_argument("--project", default=".")
    send.add_argument("--policy")
    send.add_argument("--api-url")
    send.add_argument("--idempotency-key")
    status = sub.add_parser("submission-status", help="Read only this pilot token owner's submission")
    status.add_argument("submission_id")
    status.add_argument("--api-url")
    register = sub.add_parser("register", help="Save or submit a new pinned skill source for maintainer review")
    register.add_argument("skill", help="Explicit small source-reference JSON; no project scanning")
    register.add_argument("--project", required=True)
    register.add_argument("--contributor", required=True, help="Self-reported contributor label")
    register.add_argument("--policy")
    register.add_argument("--api-url")
    register.add_argument("--output")
    register.add_argument("--draft", action="store_true", help="Save a local bundle without API delivery")
    register.add_argument("--refresh-base", action="store_true", help="Explicitly create a new intake identity at the selected hub base after review")
    register.add_argument("--expected-bundle-sha256", help="Retry only the retained bundle with this canonical SHA-256; never rewrite it")
    memory_status = sub.add_parser("memory-status", help="Read the saved finding's own review and publication status")
    memory_status.add_argument("memory_id")
    memory_status.add_argument("--api-url")
    save = sub.add_parser("save", help="Save an explicit minimal finding locally; scoped policy and token permit one delivery")
    save.add_argument("skill_id")
    save.add_argument("--project", required=True)
    save.add_argument("--finding", required=True, help="Small explicit JSON finding; no project scan")
    save.add_argument("--source-manifest", help="Use the exact verified fetch-source manifest and its original pins")
    save.add_argument("--policy")
    save.add_argument("--api-url")
    flush = sub.add_parser("flush", help="Explicitly retry at most three locally saved findings with their original identity")
    flush.add_argument("--project", required=True)
    flush.add_argument("--policy")
    flush.add_argument("--api-url")
    flush.add_argument("--limit", type=int, choices=(1, 2, 3), default=1)
    flush.add_argument("--fingerprint", dest="selected_fingerprint", help="Retry only the exact saved finding fingerprint; never scan the queue")
    recall = sub.add_parser("memories", help="Read published observations for the exact skill/source version and environment")
    recall.add_argument("skill_id")
    recall.add_argument("--project")
    recall.add_argument("--source-manifest", help="Recall findings for this explicit verified acquired source; requires --project")
    recall.add_argument("--index", help="Explicit local file or HTTPS published memory index")
    recall.add_argument("--limit", type=int, default=20, choices=range(1, 51))
    recall.add_argument("--offset", type=int, default=0)
    recall.add_argument("--hub-commit", help="Keep finding pagination on the original published Hub generation")
    environment_options(recall)
    sub.add_parser("validate-catalog", help="Validate the chosen catalog without executing recipe code")
    return parser


def extract_global(argv):
    """Keep global switches usable after subcommands without parsing stdin."""
    argv = list(argv)
    json_mode = "--json" in argv
    argv = [argument for argument in argv if argument != "--json"]
    # Accept global switches consistently before or after a command.
    switches = [option for option in ("--offline", "--refresh") if option in argv]
    argv = switches + [argument for argument in argv if argument not in switches]
    catalog = None
    for index, argument in enumerate(argv):
        if argument == "--catalog":
            if index + 1 >= len(argv):
                raise RshError("invalid_arguments", "--catalog requires a location.")
            catalog = argv[index + 1]
            del argv[index:index + 2]
            break
        if argument.startswith("--catalog="):
            catalog = argument.split("=", 1)[1]
            del argv[index]
            break
    return argv, json_mode, catalog


def catalog_handoff(result, catalog_location, offline):
    """Keep only the selected catalog/offline context on acquisition command arrays."""
    targets = [(result, key) for key in ("fetch_source_args", "fetch_args", "prepare_args") if key in result]
    source_plan = result.get("source_acquisition")
    if isinstance(source_plan, dict) and "fetch_args" in source_plan:
        targets.append((source_plan, "fetch_args"))
    rows = result.get("results")
    if isinstance(rows, list):
        targets.extend((row, "prepare_args") for row in rows
                       if isinstance(row, dict) and "prepare_args" in row)
    commands = {"fetch_source_args": "fetch-source", "fetch_args": "fetch-source", "prepare_args": "prepare"}
    targets = [(target, key) for target, key in targets if isinstance(target[key], list)
               and target[key] and target[key][0] == commands[key]]
    if not targets:
        return result
    prefix = ["--offline"] if offline else []
    if catalog_location:
        location = str(catalog_location)
        if location.startswith(("https://", "http://")):
            require_url(location, local_http=True)
            query = urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query, keep_blank_values=True)
            if (acquisition.SECRET.search(urllib.parse.unquote(location))
                    or any(acquisition.SECRET_QUERY_KEY.search(key) or acquisition.SECRET.search(value) for key, value in query)):
                for target, key in targets:
                    target.pop(key, None)
                result["catalog_handoff"] = {"status": "requires_private_catalog_selector",
                    "reason_code": "catalog_selector_contains_credentials",
                    "message": "Acquisition arguments were omitted to avoid echoing credentials. Reapply the original catalog privately."}
                return result
        else:
            location = str(Path(location).resolve())
        prefix.extend(["--catalog", location])
    for target, key in targets:
        target[key] = prefix + target[key]
    return result


def execute(args, catalog_location):
    catalog_location = catalog_location or args.catalog
    if args.offline and args.command in ("submit", "submission-status"):
        raise RshError("offline_submission_unavailable", "Patch submission and its remote status require an explicit online request.",
                       status="blocked", network_performed=False, next_action="keep_local_draft_and_retry_without_offline")
    if args.command == "setup":
        return setup.configure(args.project, allow_public_memory=args.allow_public_memory, local_only=args.local_only,
                               skill_ids=args.skill, kinds=args.kind)
    if args.command == "setup-check":
        return setup.check(args.project, api_url=args.api_url, check_api=args.check_api, offline=args.offline)
    if args.command == "submission-status":
        return contributions.submission_status(args.submission_id, api_url=args.api_url)
    if args.command == "memory-status":
        if args.offline:
            raise RshError("offline_status_unavailable", "Memory status requires an explicit online request.")
        return memories.status(args.memory_id, api_url=args.api_url)
    if args.command == "flush":
        return memories.flush(args.project, policy_path=args.policy, api_url=args.api_url, limit=args.limit, offline=args.offline,
                              selected_fingerprint=args.selected_fingerprint)
    if args.command == "register" and args.expected_bundle_sha256 is not None:
        # This retry selects an already saved identity; no catalog refresh is needed.
        return intake.register({}, args.skill, args.project, contributor=args.contributor, policy_path=args.policy,
                               api_url=args.api_url, output=args.output, draft=args.draft, offline=args.offline,
                               refresh_base=args.refresh_base, expected_bundle_sha256=args.expected_bundle_sha256)
    source_manifest = getattr(args, "source_manifest", None)
    if source_manifest and (catalog_location or not getattr(args, "project", None)):
        raise RshError("invalid_arguments", "--source-manifest requires --project and cannot be combined with --catalog.",
                       network_performed=False)
    environment = {}
    if getattr(args, "environment", None):
        environment = read_json(args.environment)
        if not isinstance(environment, dict):
            raise RshError("invalid_environment", "Environment file must contain a JSON object.")
    for field in ("runtime", "runtime_version", "robot", "controller", "observation", "os", "python", "architecture"):
        if getattr(args, field, None) is not None:
            environment[field] = getattr(args, field)
    fallback_reason = None
    if args.command == "find" and not catalog_location and not args.offline:
        try:
            return catalog_handoff(remote_catalog.search(args.query, environment, args.limit, refresh=args.refresh,
                                         offset=args.offset, hub_commit=args.hub_commit, query_mode=args.query_mode), None, args.offline)
        except (RshError, OSError, ValueError, TypeError) as error:
            if isinstance(error, RshError) and error.result.get("reason_code") in (
                    "catalog_generation_changed", "invalid_pagination", "invalid_hub_commit", "query_too_broad",
                    "invalid_query_mode", "invalid_task_query", "unsupported_task_query"):
                raise
            fallback_reason = "public_search_unavailable"
    catalog = None
    if source_manifest:
        try:
            catalog = acquisition.catalog_from_manifest(source_manifest, args.project, args.skill_id)
        except RshError as error:
            error.result["network_performed"] = False
            raise
    if not catalog_location and args.command == "register" and not args.offline:
        try:
            catalog = remote_catalog.current_catalog()
        except (RshError, OSError, ValueError, TypeError):
            fallback_reason = "public_version_unavailable"
    skill_id = getattr(args, "skill_id", None)
    if args.command == "submit":
        skill_id = read_json(args.bundle).get("skill_id")
    if not catalog_location and skill_id and catalog is None:
        # A prepared project's original source/version wins over later publication.
        if getattr(args, "project", None):
            pinned = pinned_project_catalog({"schema_version": "1", "records": []}, args.project, skill_id)
            if pinned.get("catalog_origin") == "project_lock":
                catalog = pinned
        if catalog is None:
            try:
                catalog = remote_catalog.selected_catalog(skill_id, offline=args.offline, refresh=args.refresh,
                                                           persist=not getattr(args, "plan", False))
            except (RshError, OSError, ValueError, TypeError):
                fallback_reason = "public_record_unavailable"
    if catalog is None:
        latest = args.command in ("find", "inspect", "memories", "register")
        catalog = load_discovery(catalog_location, offline=args.offline, refresh=args.refresh, latest=latest)
    if fallback_reason:
        catalog["discovery_fallback_reasons"] = [fallback_reason]
    if args.command == "find":
        return catalog_handoff(find(catalog, args.query, environment, args.limit, offset=args.offset, hub_commit=args.hub_commit,
                                    query_mode=args.query_mode),
                               catalog_location, args.offline)
    if args.command == "register":
        return intake.register(catalog, args.skill, args.project, contributor=args.contributor, policy_path=args.policy,
                               api_url=args.api_url, output=args.output, draft=args.draft, offline=args.offline, refresh_base=args.refresh_base)
    if args.command == "inspect":
        result = inspect(catalog, args.skill_id)
        if catalog_location:
            # A private/custom catalog is not permission to send its identities
            # to the Hub or associate it with a shared local finding index.
            result["findings"] = {"status": "unknown", "reason_code": "explicit_catalog_requires_findings_selection",
                "interpretation": "data_only", "applicability": "needs_applicability_check", "automatic": False,
                "results": [], "total": None, "coverage": {"complete": False}, "limit": 3, "offset": 0, "next": None,
                "execution_performed": False, "network_performed": False,
                "next_action": "choose_findings_index_and_query_memories"}
        else:
            result["findings"] = memories.for_selection(catalog, args.skill_id, environment,
                                                       offline=args.offline, refresh=args.refresh)
        return catalog_handoff(result, catalog_location, args.offline)
    if args.command == "fetch-source":
        return catalog_handoff(acquisition.fetch_source(catalog, args.skill_id, args.project,
                                        expected_source_revision=args.expected_source_revision,
                                        expected_source_sha256=args.expected_source_sha256,
                                        plan=args.plan, offline=args.offline), catalog_location, args.offline)
    if args.command == "prepare":
        if args.download_only and args.install_deps:
            raise RshError("invalid_arguments", "--download-only cannot be combined with --install-deps.")
        if not catalog_location:
            catalog = pinned_project_catalog(catalog, args.project, args.skill_id)
        selected = lookup_preparation(catalog, args.skill_id)
        if ((args.expected_source_commit and args.expected_source_commit != selected["source"]["commit"])
                or (args.expected_record_version and args.expected_record_version != selected["maintenance"]["record_version"])):
            raise RshError("selected_recipe_changed", "Catalog selection differs from the explicitly selected source or recipe version.",
                           next_action="inspect_selected_version_or_use_original_catalog", execution_performed=False)
        return prepare(catalog, args.skill_id, args.project, environment, install_deps=args.install_deps,
                       plan=args.plan, download_only=args.download_only, source_archive=args.source_archive)
    if args.command in ("bundle", "create-patch-bundle"):
        return contributions.create_bundle(catalog, args.skill_id, args.patch, args.metadata, args.output,
                                            args.project, policy_path=args.policy, hub_commit=args.hub_commit)
    if args.command == "submit":
        return contributions.submit(catalog, args.bundle, args.project, policy_path=args.policy,
                                    api_url=args.api_url, idempotency_key=args.idempotency_key)
    if args.command == "save":
        return memories.save(catalog, args.skill_id, args.project, args.finding,
                             policy_path=args.policy, api_url=args.api_url, offline=args.offline)
    if args.command == "memories":
        return memories.query(catalog, args.skill_id, environment, project=args.project, index=args.index,
                              offline=args.offline, refresh=args.refresh, limit=args.limit, offset=args.offset, hub_commit=args.hub_commit)
    return {"status": "ready", "records": len(catalog["records"]), "reason_code": "catalog_valid",
            "execution_performed": False}


def main(argv=None):
    supplied = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in supplied
    command = None
    try:
        remaining, json_mode, catalog_location = extract_global(supplied)
        parser = build_parser()
        if json_mode and any(option in remaining for option in ("--help", "-h")):
            result = {"status": "ready", "help": parser.format_help()}
        else:
            args = parser.parse_args(remaining)
            command = args.command
            result = execute(args, catalog_location or args.catalog)
    except RshError as exc:
        result = exc.result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Stable user-facing contract, no tracebacks or accidental environment values.
        result = {"status": "failed", "reason_code": "unexpected_local_error",
                  "message": f"Local operation failed ({type(exc).__name__}).",
                  "network_performed": None,
                  "next_action": "check_files_and_report_reproduction"}
    # Saving a reusable observation is optional and must not fail the user's task.
    if command in ("save", "flush") and result.get("status") not in ("ready", "stored", "local_saved"):
        result = {**result, "status": "skipped", "network_performed": result.get("network_performed"), "next_action": "continue_user_task"}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if json_mode:
        print(rendered)
    else:
        print(rendered)
    return 0 if result.get("status") in ("ready", "stored", "local_saved", "skipped", "submitted", "checking", "needs_changes", "pending_review",
                                        "merged", "published", "rejected", "publish_failed", "superseded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
