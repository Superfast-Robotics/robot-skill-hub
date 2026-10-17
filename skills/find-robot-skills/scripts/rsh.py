#!/usr/bin/env python3
"""Robot Skill Hub standalone entry point. Requires Python 3.10+, no extra packages."""
from __future__ import annotations

import argparse
import json
import sys

from rshlib import contributions, memories
from rshlib.core import RshError, find, inspect, load_catalog, lookup, read_json
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
    search = sub.add_parser("find", help="Find at most three candidate recipes without running their code")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=3, choices=(1, 2, 3))
    environment_options(search)
    detail = sub.add_parser("inspect", help="Read source, requirements and verification evidence")
    detail.add_argument("skill_id")
    prep = sub.add_parser("prepare", help="Download pinned source and create an isolated environment; never run task")
    prep.add_argument("skill_id")
    prep.add_argument("--project", required=True)
    prep.add_argument("--plan", action="store_true", help="Return planned actions; no writes or downloads")
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
    memory_status = sub.add_parser("memory-status", help="Read the saved finding's own review and publication status")
    memory_status.add_argument("memory_id")
    memory_status.add_argument("--api-url")
    save = sub.add_parser("save", help="Save an explicit minimal finding locally; scoped policy and token permit one delivery")
    save.add_argument("skill_id")
    save.add_argument("--project", required=True)
    save.add_argument("--finding", required=True, help="Small explicit JSON finding; no project scan")
    save.add_argument("--policy")
    save.add_argument("--api-url")
    flush = sub.add_parser("flush", help="Explicitly retry at most three locally saved findings with their original identity")
    flush.add_argument("--project", required=True)
    flush.add_argument("--policy")
    flush.add_argument("--api-url")
    flush.add_argument("--limit", type=int, choices=(1, 2, 3), default=1)
    recall = sub.add_parser("memories", help="Read published observations for the exact skill/source version and environment")
    recall.add_argument("skill_id")
    recall.add_argument("--project")
    recall.add_argument("--index", help="Explicit local file or HTTPS published memory index")
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


def execute(args, catalog_location):
    if args.command == "submission-status":
        return contributions.submission_status(args.submission_id, api_url=args.api_url)
    if args.command == "memory-status":
        if args.offline:
            raise RshError("offline_status_unavailable", "Memory status requires an explicit online request.")
        return memories.status(args.memory_id, api_url=args.api_url)
    if args.command == "flush":
        return memories.flush(args.project, policy_path=args.policy, api_url=args.api_url, limit=args.limit, offline=args.offline)
    latest = args.command in ("find", "inspect", "memories")
    catalog = load_discovery(catalog_location, offline=args.offline, refresh=args.refresh, latest=latest)
    environment = {}
    if getattr(args, "environment", None):
        environment = read_json(args.environment)
        if not isinstance(environment, dict):
            raise RshError("invalid_environment", "Environment file must contain a JSON object.")
    for field in ("runtime", "runtime_version", "robot", "controller", "observation", "os", "python", "architecture"):
        if getattr(args, field, None) is not None:
            environment[field] = getattr(args, field)
    if args.command == "find":
        return find(catalog, args.query, environment, args.limit)
    if args.command == "inspect":
        return inspect(catalog, args.skill_id)
    if args.command == "prepare":
        if args.download_only and args.install_deps:
            raise RshError("invalid_arguments", "--download-only cannot be combined with --install-deps.")
        if not catalog_location:
            catalog = pinned_project_catalog(catalog, args.project, args.skill_id)
        selected = lookup(catalog, args.skill_id)
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
                              offline=args.offline, refresh=args.refresh)
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
                  "next_action": "check_files_and_report_reproduction"}
    # Saving a reusable observation is optional and must not fail the user's task.
    if command in ("save", "flush") and result.get("status") not in ("ready", "stored", "local_saved"):
        result = {**result, "status": "skipped", "network_performed": False, "next_action": "continue_user_task"}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if json_mode:
        print(rendered)
    else:
        print(rendered)
    return 0 if result.get("status") in ("ready", "stored", "local_saved", "skipped", "submitted", "checking", "needs_changes", "pending_review",
                                        "merged", "published", "rejected", "publish_failed", "superseded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
