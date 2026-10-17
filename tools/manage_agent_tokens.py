"""Maintain a private, complete Worker caller registry without printing tokens.

This tool makes local changes only. Cloudflare secrets are write-only: importing
or adopting a registry requires the operator to confirm that no callers are
missing. Export a complete snapshot before explicitly uploading it with Wrangler.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from contextlib import contextmanager

LOCAL = Path(__file__).resolve().parents[1] / ".local"
DEFAULT_REGISTRY = LOCAL / "submission-tokens.registry.json"


def digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def principal_hash(principal):
    return digest("rsh-principal-v1\0" + principal)


def valid_principal(principal):
    if not isinstance(principal, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", principal):
        raise ValueError("Principal must contain 1..80 ASCII letters, digits, underscores, dots or hyphens.")


def private_path(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(LOCAL.resolve()):
        raise ValueError("Registry, export and token files must stay inside the Git-ignored .local directory.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def validate(entries):
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("Registry must contain 1..100 entries.")
    hashes = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"principal_id", "sha256", "disabled"}:
            raise ValueError("Registry entry contains unsupported fields.")
        valid_principal(entry.get("principal_id"))
        value = entry.get("sha256")
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) or value in hashes:
            raise ValueError("Registry token hashes must be unique lowercase SHA-256 values.")
        if "disabled" in entry and type(entry["disabled"]) is not bool:
            raise ValueError("Registry disabled must be a boolean.")
        hashes.add(value)
    return entries


def read_registry(path):
    return validate(json.loads(private_path(path).read_text(encoding="utf-8-sig")))


def encode(entries):
    return (json.dumps(validate(entries), indent=2, sort_keys=True) + "\n").encode("utf-8")


def exclusive_write(path, content):
    path = private_path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def replace_registry(path, entries):
    path = private_path(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        exclusive_write(temporary, encode(entries))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def registry_lock(path):
    lock = private_path(path).with_name(Path(path).name + ".lock")
    try:
        exclusive_write(lock, b"local registry mutation in progress\n")
    except FileExistsError:
        raise ValueError("Registry is locked. Finish the other command; remove a stale lock only after checking its process.") from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def adopt(path, principal, token_file, receipt_file, complete):
    if not complete:
        raise ValueError("Cloudflare secrets cannot be read back. Confirm the registry is complete before adoption.")
    valid_principal(principal)
    token = private_path(token_file).read_text(encoding="utf-8-sig").strip()
    if not re.fullmatch(r"rsh_[A-Za-z0-9_-]{43}", token):
        raise ValueError("Expected a generated 256-bit Hub client token.")
    receipt = json.loads(Path(receipt_file).read_text(encoding="utf-8-sig"))
    if receipt.get("principal_id") != principal_hash(principal):
        raise ValueError("The receipt does not belong to this principal; adoption stopped.")
    with registry_lock(path):
        exclusive_write(path, encode([{"principal_id": principal, "sha256": digest(token)}]))


def import_registry(path, input_json, complete):
    if not complete:
        raise ValueError("Confirm that the imported registry includes every configured caller.")
    entries = validate(json.loads(private_path(input_json).read_text(encoding="utf-8-sig")))
    with registry_lock(path):
        exclusive_write(path, encode(entries))


def issue(path, principal, token_file, rotate=False):
    valid_principal(principal)
    token_file = private_path(token_file)
    with registry_lock(path):
        entries = read_registry(path)
        previous = [entry for entry in entries if entry["principal_id"] == principal]
        if bool(previous) != rotate:
            raise ValueError("Use rotate for an existing principal, or add for a new principal.")
        token = "rsh_" + secrets.token_urlsafe(32)
        updated = [{**entry, **({"disabled": True} if entry["principal_id"] == principal else {})} for entry in entries]
        updated.append({"principal_id": principal, "sha256": digest(token)})
        validate(updated)
        exclusive_write(token_file, token.encode("utf-8"))
        try:
            replace_registry(path, updated)
        except Exception:
            token_file.unlink(missing_ok=True)
            raise


def revoke(path, principal):
    valid_principal(principal)
    with registry_lock(path):
        entries = read_registry(path)
        if not any(entry["principal_id"] == principal for entry in entries):
            raise ValueError("Principal not found; registry was not changed.")
        replace_registry(path, [{**entry, **({"disabled": True} if entry["principal_id"] == principal else {})} for entry in entries])


def summary(entries):
    return {"principals": [{"principal_id": principal,
             "active_tokens": sum(entry.get("disabled") is not True for entry in entries if entry["principal_id"] == principal)}
            for principal in sorted({entry["principal_id"] for entry in entries})], "entry_count": len(entries)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = parser.add_subparsers(dest="command", required=True)
    adopting = commands.add_parser("adopt-pilot", help="Adopt a known single-caller deployment; never infer completeness.")
    adopting.add_argument("--principal-id", default="pilot-1")
    adopting.add_argument("--token-file", type=Path, default=LOCAL / "pilot-token.secret")
    adopting.add_argument("--receipt-file", type=Path, required=True, help="Previously verified server memory or submission receipt.")
    adopting.add_argument("--confirm-complete-registry", action="store_true")
    importing = commands.add_parser("import", help="Import the full operator-held hashed configuration.")
    importing.add_argument("--input-json", type=Path, required=True)
    importing.add_argument("--confirm-complete-registry", action="store_true")
    for name in ("add", "rotate"):
        command = commands.add_parser(name)
        command.add_argument("principal_id")
        command.add_argument("--token-file", type=Path, required=True)
    commands.add_parser("list")
    revoking = commands.add_parser("revoke")
    revoking.add_argument("principal_id")
    exporting = commands.add_parser("export")
    exporting.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "adopt-pilot":
            adopt(args.registry, args.principal_id, args.token_file, args.receipt_file, args.confirm_complete_registry)
        elif args.command == "import":
            import_registry(args.registry, args.input_json, args.confirm_complete_registry)
        elif args.command in ("add", "rotate"):
            issue(args.registry, args.principal_id, args.token_file, args.command == "rotate")
        elif args.command == "revoke":
            revoke(args.registry, args.principal_id)
        elif args.command == "export":
            target = private_path(args.output_json)
            if target == private_path(args.registry):
                raise ValueError("Export must use a separate file from the registry.")
            with registry_lock(args.registry):
                exclusive_write(target, encode(read_registry(args.registry)))
        print(json.dumps({"status": "local_only", **summary(read_registry(args.registry))}, sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        # No token or registry contents are included in errors.
        print(json.dumps({"status": "error", "error": str(error) if isinstance(error, ValueError) else type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
