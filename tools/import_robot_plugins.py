"""Check finite ROS 2 plugin registrations or emit separate new-skill drafts.

Offline only. This checks a deliberately small literal C++/CMake/XML subset,
not compilation, CMake evaluation, plugin loading or runtime compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
from rshlib.intake import validate_published_reference, validate_skill
from rshlib.core import RshError

MAX_FILE = 2 * 1024 * 1024
MACROS = {"PLUGINLIB_EXPORT_CLASS", "CLASS_LOADER_REGISTER_CLASS"}
QUALIFIED = r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*"
RAW_STRING = re.compile(r'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(')
RAW_PREFIX = re.compile(r'(?:u8|u|U|L)?R"')
UNKNOWN = {key: "unknown" for key in ("runtime", "runtime_version", "robot", "controller", "observation", "os")}
LICENSE_MARKERS = {
    "Apache-2.0": ("Apache License", "Version 2.0", "END OF TERMS AND CONDITIONS"),
    "MIT": ("Permission is hereby granted, free of charge", "THE SOFTWARE IS PROVIDED"),
    "BSD-2-Clause": ("Redistribution and use", "THIS SOFTWARE IS PROVIDED"),
    "BSD-3-Clause": ("Redistribution and use", "Neither the name", "THIS SOFTWARE IS PROVIDED"),
}


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(value):
    need(isinstance(value, str) and value and "\\" not in value and ":" not in value
         and not PurePosixPath(value).is_absolute() and all(part not in ("", ".", "..") for part in value.split("/")), "Unsafe repository-relative path")
    return value


def read_json(path, maximum=2 * 1024 * 1024):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, "Missing, linked or oversized JSON input")
    return json.loads(path.read_text(encoding="utf-8"))


def checked_files(project, cache):
    need(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project["id"]) and re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project["repository"])
         and re.fullmatch(r"[a-f0-9]{40}", project["commit"]), "Project requires a canonical repository and immutable commit")
    pins = project["files"]
    need(isinstance(pins, dict) and 0 < len(pins) <= 60, "A finite file-pin map is required")
    data = {}
    cache = Path(cache).absolute()
    for relative, pin in pins.items():
        safe_path(relative)
        need(isinstance(pin, dict) and type(pin.get("bytes")) is int and 0 < pin["bytes"] <= MAX_FILE
             and re.fullmatch(r"[a-f0-9]{64}", str(pin.get("sha256", "")))
             and re.fullmatch(r"[a-f0-9]{40}", str(pin.get("git_blob_sha1", ""))), "Every file needs exact bytes, SHA-256 and Git blob pins")
        path = cache / project["id"] / project["commit"] / relative
        need(not any(p.is_symlink() for p in [path, *path.parents]) and path.resolve().is_relative_to(cache.resolve())
             and path.is_file() and path.stat().st_size == pin["bytes"], "Missing, linked or changed pinned cache file: " + relative)
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        need(digest(raw) == pin["sha256"] and blob == pin["git_blob_sha1"], "Pinned file digest changed: " + relative)
        text = raw.decode("utf-8-sig")
        need("\0" not in text, "Binary input is outside the text-only subset")
        data[relative] = text
    return data


def cpp_code(text):
    """Blank comments/literals, retaining offsets; collect comments as license data."""
    need(not re.search(r"\\[ \t]*(?:\r\n?|\n)", text), "C++ translation-line splices are outside the reviewed subset")
    out, comments, i = list(text), [], 0
    while i < len(text):
        start = i
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            comments.append((start, text[start:i]))
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            need(end >= 0, "Unterminated C++ comment")
            i = end + 2
            comments.append((start, text[start:i]))
        else:
            raw = RAW_STRING.match(text, i)
            need(raw or not RAW_PREFIX.match(text, i), "Unsupported C++ raw-string delimiter")
            if raw:
                closing = ")" + raw[1] + '"'
                end = text.find(closing, raw.end())
                need(end >= 0, "Unterminated C++ raw string")
                i = end + len(closing)
            elif text[i] in "\"'":
                quote, i = text[i], i + 1
                while i < len(text) and text[i] != quote:
                    i += 2 if text[i] == "\\" else 1
                need(i < len(text), "Unterminated C++ string/character literal")
                i += 1
            else:
                i += 1
                continue
        for position in range(start, i):
            if out[position] not in "\r\n":
                out[position] = " "
    return "".join(out), comments


def cpp_registration(text, registration):
    code, comments = cpp_code(text)
    occurrences = list(re.finditer(r"\b(?:PLUGINLIB_EXPORT_CLASS|CLASS_LOADER_REGISTER_CLASS)\b", code))
    need(len(occurrences) == 1, "Exactly one supported literal C++ export is required")
    match = occurrences[0]
    call = re.match(r"(" + "|".join(sorted(MACROS)) + r")\s*\(\s*(" + QUALIFIED + r")\s*,\s*(" + QUALIFIED + r")\s*\)", code[match.start():])
    need(call and call.groups() == (registration["macro"], registration["type"], registration["base_class_type"]), "C++ export differs from the selected XML class/base")
    depth = 0
    for line in code[:match.start()].splitlines():
        directive = re.match(r"\s*#\s*(\w+)", line)
        if directive:
            if directive[1] in ("if", "ifdef", "ifndef"):
                depth += 1
            elif directive[1] == "endif":
                depth -= 1
    prefix = code[code.rfind("\n", 0, match.start()) + 1:match.start()]
    need(depth == 0 and "#" not in prefix and code[:match.start()].count("{") == code[:match.start()].count("}"), "Conditional/preprocessor/non-global exports are outside the literal subset")
    first_code = next((i for i, c in enumerate(code) if not c.isspace()), len(code))
    return "\n".join(value for start, value in comments if start < first_code), "\n".join(value for _, value in comments)


def xml(text):
    need(not re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I), "XML DTD/entity declarations are not accepted")
    return ET.fromstring(text)


def cmake_commands(text):
    """Lex commands without evaluating them; bracket/quoted text is never code."""
    tokens, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        bracket = re.match(r"(#?)\[(=*)\[", text[i:])
        if bracket:
            end = text.find("]" + bracket[2] + "]", i + bracket.end())
            need(end >= 0, "Unterminated CMake bracket text")
            if not bracket[1]:
                tokens.append(("bracket", text[i + bracket.end():end]))
            i = end + len(bracket[2]) + 2
        elif text[i] == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text[i] == '"':
            start, i = i + 1, i + 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            need(i < len(text), "Unterminated CMake quote")
            tokens.append(("quoted", text[start:i]))
            i += 1
        elif text[i] in "()":
            tokens.append((text[i], text[i]))
            i += 1
        else:
            start = i
            while i < len(text) and not text[i].isspace() and text[i] not in '()#"':
                i += 1
            tokens.append(("word", text[start:i]))
    commands, i, blocks = [], 0, []
    while i < len(tokens):
        need(i + 1 < len(tokens) and tokens[i][0] == "word" and tokens[i + 1][0] == "(", "Unsupported CMake command syntax")
        name, i, depth, args = tokens[i][1].lower(), i + 2, 1, []
        while i < len(tokens) and depth:
            kind, value = tokens[i]
            depth += (kind == "(") - (kind == ")")
            if depth:
                args.append((kind, value))
            i += 1
        need(depth == 0, "Unbalanced CMake command")
        if name.startswith("end") and name[3:] in ("if", "foreach", "while", "function", "macro", "block"):
            need(blocks and blocks[-1] == name[3:], "Unbalanced CMake control block")
            blocks.pop()
        commands.append((name, args, bool(blocks)))
        if name in ("if", "foreach", "while", "function", "macro", "block"):
            blocks.append(name)
    need(not blocks, "Unclosed CMake control block")
    return commands


def cmake_registration(text, package_dir, source_path, registration, package_name):
    commands = cmake_commands(text)
    def literals(args):
        need(all(kind in ("word", "quoted") for kind, _ in args), "Selected CMake arguments must be literal")
        values = [value.replace("${PROJECT_NAME}", package_name) for _, value in args]
        need(all(value and not any(c in value for c in "$;\\") for value in values), "Unsupported dynamic selected CMake argument")
        return values
    project_commands = [(args, conditional) for name, args, conditional in commands if name == "project"]
    need(all(all("$" not in value for _, value in args) for args, _ in project_commands), "CMake project name must be declared literally")
    projects = [(literals(args), conditional) for args, conditional in project_commands]
    need(len(projects) == 1 and not projects[0][1] and projects[0][0] and projects[0][0][0] == package_name, "CMake project/package name differs")
    libraries, exports = [], []
    for name, args, conditional in commands:
        if name in ("set", "unset") and args:
            need("$" not in args[0][1] and args[0][1] != "PROJECT_NAME", "Dynamic variable names/PROJECT_NAME mutation require a separate review")
        if name in ("function", "macro") and args:
            need(args[0][1].lower() not in ("project", "add_library", "pluginlib_export_plugin_description_file"), "Overridden registration CMake commands are ambiguous")
        if name in ("set_target_properties", "set_property"):
            values = literals(args)
            separator = "PROPERTIES" if name == "set_target_properties" else "PROPERTY"
            need(separator in values, "Unsupported target-property command")
            at = values.index(separator)
            targets = values[:at] if name == "set_target_properties" else values[1:at] if values[0] == "TARGET" else []
            properties = values[at + 1::2] if name == "set_target_properties" else values[at + 1:at + 2]
            need(registration["library"] not in targets or not any(re.search(r"(?:^|_)(?:OUTPUT_NAME|PREFIX|SUFFIX|POSTFIX)(?:_|$)", prop) for prop in properties), "Selected target library naming overrides require a separate review")
        if name == "add_library":
            need(args, "Empty CMake library")
            target = literals(args[:1])[0]
            if target == registration["library"]:
                values = literals(args)
                need(not conditional and len(values) >= 3 and values[1] == "SHARED", "Selected library must be an unconditional literal SHARED target")
                sources = [safe_path(str(PurePosixPath(package_dir) / safe_path(value))) for value in values[2:]]
                need(source_path in sources, "Selected C++ file is absent from its shared-library sources")
                libraries.append(values)
        elif name == "target_sources" and args and literals(args[:1])[0] == registration["library"]:
            raise ValueError("Additional target_sources for the selected target require a separate review")
        elif name == "pluginlib_export_plugin_description_file":
            values = literals(args)
            need(not conditional and len(values) == 2, "Plugin XML export must be unconditional and literal")
            exports.append((values[0], safe_path(str(PurePosixPath(package_dir) / safe_path(values[1])))))
    need(len(libraries) == 1 and exports == [(registration["export_package"], registration["path"])], "Missing or ambiguous literal library/plugin XML export")


def observed_licenses(text):
    found = {value.strip().rstrip("*/ -") for value in re.findall(r"SPDX-License-Identifier:\s*([^\r\n]+)", text)}
    if re.search(r"Licensed under the Apache License,? (?:Version )?2\.0", text, re.I) or "END OF TERMS AND CONDITIONS" in text:
        found.add("Apache-2.0")
    if "Permission is hereby granted, free of charge" in text:
        found.add("MIT")
    if "Redistribution and use" in text:
        found.add("BSD-3-Clause" if "Neither the name" in text else "BSD-2-Clause")
    if re.search(r"GNU (?:GENERAL PUBLIC|General Public) LICENSE|GNU General Public License", text):
        found.add("LicenseRef-GPL-requires-review")
    return found


def make_draft(project, plugin, files):
    ident, registration = plugin["id"], plugin["registration"]
    need(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ident) and len(ident) <= 80, "Invalid plugin intake id")
    need(registration["macro"] in MACROS and re.fullmatch(QUALIFIED, registration["type"]) and re.fullmatch(QUALIFIED, registration["base_class_type"]), "Unsupported selected export/class names")
    for key in ("source_path", "package_path", "cmake_path"):
        safe_path(plugin[key])
    need(plugin["source_path"].endswith((".cpp", ".cc", ".cxx")), "Only selected C++ implementation files are supported")
    package_dir = str(PurePosixPath(plugin["package_path"]).parent)
    need(PurePosixPath(plugin["cmake_path"]).parent == PurePosixPath(package_dir), "Package XML and CMake must share the reviewed package directory")
    descriptor = xml(files[registration["path"]])
    need(descriptor.tag == "library" and descriptor.attrib == {"path": registration["library"]}, "Selected plugin XML must be one literal library")
    classes = [c for c in descriptor if c.tag == "class" and c.get("name") == registration["name"]]
    need(len(classes) == 1 and all(classes[0].get(k) == registration[k] for k in ("type", "base_class_type")), "Selected XML class/base is missing or ambiguous")
    package = xml(files[plugin["package_path"]])
    need(package.tag == "package" and len(package.findall("name")) == 1, "Package XML name missing or ambiguous")
    package_name = package.findtext("name")
    need(package_name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", package_name), "Invalid literal package name")
    cmake_registration(files[plugin["cmake_path"]], package_dir, plugin["source_path"], registration, package_name)
    header, comments = cpp_registration(files[plugin["source_path"]], registration)
    review = plugin["reviewed_metadata"]
    license_info = plugin["license"]
    spdx = license_info["spdx"]
    need(spdx in LICENSE_MARKERS and all(marker in files[license_info["path"]] for marker in LICENSE_MARKERS[spdx]), "Complete pinned standard license text required")
    package_licenses = {(node.text or "").strip().replace("Apache License 2.0", "Apache-2.0") for node in package.findall("license")}
    need(package_licenses == {spdx} and observed_licenses(comments) == {spdx}
         and observed_licenses(files[license_info["path"]]) == {spdx}, "Source/package/full-license conflict or incomplete source notice")
    need(license_info.get("source_notice_quotes") and all(isinstance(q, str) and q and q in header for q in license_info["source_notice_quotes"]), "Reviewed copyright/license notice is absent from the actual source header")
    provenance = plugin.get("author_provenance")
    need(isinstance(provenance, dict) and set(provenance) == set(review["authors"]), "Every reviewed author needs explicit attribution provenance")
    for author, credit in provenance.items():
        need(isinstance(credit, dict), "Invalid author provenance")
        if credit.get("kind") == "source_header":
            quote = credit.get("quote")
            need(set(credit) == {"kind", "quote"} and isinstance(quote, str) and author in quote and quote in header, "Source-header attribution quote is absent")
        elif credit.get("kind") == "package_author":
            need(set(credit) == {"kind", "path", "name"} and credit.get("path") == plugin["package_path"] and credit.get("name") == author
                 and sum(node.text == author for node in package.findall("author")) == 1, "Exact pinned package author node is absent or ambiguous")
        else:
            raise ValueError("Unsupported author provenance; package maintainers do not imply authorship")
    deps = {(node.text or "").strip() for node in package if node.tag in ("depend", "build_depend", "buildtool_depend", "exec_depend")}
    need(deps <= set(review["requirements"]["packages"]) and review["requirements"]["python"] is None, "Reviewed requirements omit a package dependency or invent Python support")
    source = project["files"][plugin["source_path"]]
    url = lambda path: project["repository"] + "/blob/" + project["commit"] + "/" + path
    draft = {"id": ident, "name": review["name"], "summary": review["summary"], "framework": review["framework"], "kind": "community_skill",
             "capabilities": review["capabilities"], "aliases": review["aliases"], "robots": review["robots"],
             "source": {"repository": project["repository"], "commit": project["commit"], "path": plugin["source_path"], "url": url(plugin["source_path"]),
                        "sha256": source["sha256"], "bytes": source["bytes"], "authors": review["authors"]},
             "license": {"spdx": spdx, "url": url(license_info["path"]), "scope": license_info["scope"]}, "artifact": {"kind": "code", "format": "cpp"},
             "requirements": review["requirements"], "invocation": {"entrypoint": "pluginlib " + registration["name"] + " (" + registration["base_class_type"] + ")", "notes": review["invocation_notes"]},
             "compatibility": [dict(UNKNOWN)], "setup_url": url(plugin["cmake_path"])}
    validate_skill(draft)
    return draft


def source_identity(record):
    source = record.get("source", {})
    repository = source.get("repository", "").rstrip("/").removesuffix(".git").casefold()
    return repository, source.get("commit") or source.get("revision"), source.get("path")


def canonical_records(root):
    managed = read_json(root / "catalog/references.json", 16 * 1024 * 1024)["records"]
    return managed + [read_json(path, 256 * 1024) for folder in ("intake", "records") for path in sorted((root / "catalog" / folder).glob("*.json"))]


def prepare(manifest, cache, root=ROOT, check=False):
    need(manifest.get("schema_version") == "1" and isinstance(manifest.get("projects"), list) and 0 < len(manifest["projects"]) <= 10, "Finite versioned project manifest required")
    existing, drafts, seen_ids, seen_sources = canonical_records(root), [], set(), set()
    need(len({p["id"] for p in manifest["projects"]}) == len(manifest["projects"]), "Duplicate project id")
    files_checked = 0
    for project in manifest["projects"]:
        files = checked_files(project, cache)
        files_checked += len(files)
        need(isinstance(project.get("plugins"), list) and 0 < len(project["plugins"]) <= 20, "Finite selected plugin list required")
        for plugin in project["plugins"]:
            draft = make_draft(project, plugin, files)
            identity, ident = source_identity(draft), draft["id"]
            need(ident not in seen_ids and identity not in seen_sources, "Duplicate manifest id/source pin")
            seen_ids.add(ident)
            seen_sources.add(identity)
            collisions = [r for r in existing if r.get("id") == ident or source_identity(r) == identity]
            if check:
                path = root / "catalog/intake" / (ident + ".json")
                need(plugin.get("owned_intake_sha256") and path.is_file() and digest(path.read_bytes()) == plugin["owned_intake_sha256"], "Owned intake is missing or differs from its reviewed exact bytes")
                record = read_json(path, 256 * 1024)
                validate_published_reference(record)
                need(len(collisions) == 1 and collisions[0] == record and source_identity(record) == identity, "Existing canonical ownership/id/source pin is ambiguous")
                normalized = {key: record[key] for key in draft if key not in ("license", "compatibility", "setup_url")}
                normalized.update(license={k: record["license"][k] for k in draft["license"]}, compatibility=[{k: combo[k] for k in UNKNOWN} for combo in record["compatibility"]], setup_url=record["access"]["setup_url"])
                need(normalized == draft and record["compatibility"] == [{**UNKNOWN, "status": "unknown"}] and record["license"]["verified"] is True
                     and record["evidence"]["level"] == "source_reviewed" and record["evidence"]["runtime_verification"] == "not_run"
                     and record["access"]["mode"] == "source_reference" and record["access"]["hub_prepare"] is False, "Owned intake differs from the reviewed source-only structural metadata")
            else:
                need(not collisions, "Draft would duplicate a canonical id/source pin; use --check for an already owned intake")
            drafts.append(draft)
    return drafts, files_checked


def write_drafts(drafts, output, root=ROOT):
    supplied = Path(output).absolute()
    need(not any(path.is_symlink() for path in [supplied, *supplied.parents]), "Output cannot use symlinked paths")
    output, root = supplied.resolve(), root.resolve()
    need(not output.exists() and output.parent.is_dir() and (not output.is_relative_to(root) or (root / ".local") in output.parents), "Use a fresh output directory outside the repository or under its .local directory")
    for draft in drafts:
        validate_skill(draft)
    need(len({draft["id"] for draft in drafts}) == len(drafts), "Duplicate output id")
    encoded = [(draft["id"] + ".json", (json.dumps(draft, ensure_ascii=False, indent=2) + "\n").encode("utf-8")) for draft in drafts]
    need(all(len(raw) <= 16 * 1024 for _, raw in encoded), "Draft metadata exceeds its bounded intake size")
    output.mkdir(exist_ok=False)
    for name, raw in encoded:
        with (output / name).open("xb") as stream:
            stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/plugin-projects.json")
    parser.add_argument("--cache", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-directory", type=Path)
    args = parser.parse_args()
    try:
        drafts, files = prepare(read_json(args.manifest), args.cache, check=args.check)
        if args.output_directory is not None:
            write_drafts(drafts, args.output_directory)
        print(json.dumps({"status": "checked_existing_intakes" if args.check else "draft_metadata_written", "plugins": [d["id"] for d in drafts], "pinned_files_checked": files,
                          "registration_evidence": "literal_registration_consistent", "publication_performed": False, "network_performed": False, "execution_performed": False, "ownership_transferred": False}))
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError, RshError) as error:
        print(json.dumps({"status": "rejected", "message": str(error), "publication_performed": False, "network_performed": False, "execution_performed": False}), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
