"""Registration/data contracts; no compiler, package, plugin or network is used."""
import copy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_robot_plugins as importer
from rshlib.intake import validate_bundle, validate_skill

MIT = """MIT License
Copyright 2026 Fixture Robotics
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
HEADER = "// Copyright 2026 Fixture Robotics\n// SPDX-License-Identifier: MIT\n"
EXPORT = "PLUGINLIB_EXPORT_CLASS(demo::Controller, controller_interface::ControllerInterface)\n"


class RobotPluginImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root, self.cache = self.folder / "repository", self.folder / "cache"
        for sub in ("intake", "records"):
            (self.root / "catalog" / sub).mkdir(parents=True)
        (self.root / "catalog/references.json").write_text('{"records": []}', encoding="utf-8")
        self.project = {"id": "fixture-plugins", "repository": "https://github.com/example/robot_plugins", "commit": "a" * 40, "files": {}, "plugins": []}
        self.data = {
            "demo_pkg/src/controller.cpp": HEADER + "#include <pluginlib/class_list_macros.hpp>\n" + EXPORT,
            "demo_pkg/plugin.xml": '<library path="demo_controller"><class name="demo/Controller" type="demo::Controller" base_class_type="controller_interface::ControllerInterface"><description>Fixture only.</description></class></library>',
            "demo_pkg/package.xml": '<package format="3"><name>demo_pkg</name><version>0.1.0</version><license>MIT</license><buildtool_depend>ament_cmake</buildtool_depend><depend>controller_interface</depend><depend>pluginlib</depend><test_depend>unused_fixture_test</test_depend></package>',
            "demo_pkg/CMakeLists.txt": 'project(demo_pkg)\nadd_library(demo_controller SHARED src/controller.cpp)\npluginlib_export_plugin_description_file(controller_interface plugin.xml)\n',
            "LICENSE": MIT}
        self.plugin = {"id": "fixture-controller", "source_path": "demo_pkg/src/controller.cpp", "package_path": "demo_pkg/package.xml", "cmake_path": "demo_pkg/CMakeLists.txt",
                       "registration": {"path": "demo_pkg/plugin.xml", "name": "demo/Controller", "type": "demo::Controller", "base_class_type": "controller_interface::ControllerInterface", "library": "demo_controller", "export_package": "controller_interface", "macro": "PLUGINLIB_EXPORT_CLASS"},
                       "author_provenance": {"Fixture Robotics": {"kind": "source_header", "quote": "Copyright 2026 Fixture Robotics"}},
                       "license": {"path": "LICENSE", "spdx": "MIT", "scope": "Synthetic fixture source only; no runtime or hardware claim.", "source_notice_quotes": ["Copyright 2026 Fixture Robotics", "SPDX-License-Identifier: MIT"]},
                       "reviewed_metadata": {"name": "Fixture controller", "summary": "Synthetic controller registration contract fixture; not a robot execution claim.", "framework": "fixture-plugins", "capabilities": ["controller-plugin"], "aliases": ["demo/Controller"], "robots": ["unspecified robot"], "authors": ["Fixture Robotics"], "requirements": {"python": None, "packages": ["ament_cmake", "controller_interface", "pluginlib"], "hardware": [], "system": [], "notes": "Fixture only; a configured host and full package would be required."}, "invocation_notes": "Declared plugin registration only; no compiler, loader or controller was used."}}
        self.project["plugins"].append(self.plugin)
        self.manifest = {"schema_version": "1", "projects": [self.project]}
        for path, text in self.data.items():
            self.change(path, text)

    def change(self, relative, text, repin=True):
        raw = text.encode("utf-8")
        path = self.cache / self.project["id"] / self.project["commit"] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.data[relative] = text
        if repin:
            self.project["files"][relative] = {"sha256": importer.digest(raw), "bytes": len(raw), "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

    def prepare(self, check=False):
        return importer.prepare(self.manifest, self.cache, self.root, check)

    def rejected(self, fragment):
        with self.assertRaisesRegex((ValueError, importer.ET.ParseError), fragment):
            self.prepare()

    def owned(self):
        draft = self.prepare()[0][0]
        record = copy.deepcopy(draft)
        record.pop("setup_url")
        record["license"]["verified"] = True
        record["compatibility"] = [{**importer.UNKNOWN, "status": "unknown"}]
        record.update(access={"mode": "source_reference", "hub_prepare": False, "instructions": "Inspect upstream before integrating.", "setup_url": draft["setup_url"]},
                      evidence={"level": "source_reviewed", "runtime_verification": "not_run", "checked_at": "2026-10-18", "inspection": "Fixture registration only."},
                      maintenance={"record_version": "reviewed-fixture", "last_checked": "2026-10-18", "upstream_status": "source_pinned"})
        path = self.root / "catalog/intake" / (record["id"] + ".json")
        raw = (json.dumps(record, indent=2) + "\n").encode()
        path.write_bytes(raw)
        self.plugin["owned_intake_sha256"] = importer.digest(raw)
        return record, path

    def test_generated_file_is_actual_registration_input_and_has_no_runtime_claim(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("No network")), mock.patch.object(subprocess, "run", side_effect=AssertionError("No upstream process")):
            drafts, count = self.prepare()
            output = self.folder / "drafts"
            importer.write_drafts(drafts, output, self.root)
        self.assertEqual(5, count)
        draft = json.loads((output / "fixture-controller.json").read_text(encoding="utf-8"))
        validate_skill(draft)
        validate_bundle({"schema_version": "1", "base": {"hub_commit": "b" * 40}, "skill": draft,
                         "attribution": {"contributor_label": "Fixture maintainer", "preserve_upstream_attribution": True}, "publication": {"public_submission_allowed": True}})
        self.assertEqual([importer.UNKNOWN], draft["compatibility"])
        self.assertIsNone(draft["requirements"]["python"])
        self.assertFalse({"evidence", "access", "maintenance"} & draft.keys())
        self.assertNotIn("verified", draft["license"])
        self.assertEqual({"kind": "code", "format": "cpp"}, draft["artifact"])

    def test_second_supported_macro_and_literal_project_name_substitution(self):
        self.plugin["registration"].update(macro="CLASS_LOADER_REGISTER_CLASS", library="demo_pkg")
        self.change("demo_pkg/src/controller.cpp", HEADER + EXPORT.replace("PLUGINLIB_EXPORT_CLASS", "CLASS_LOADER_REGISTER_CLASS"))
        self.change("demo_pkg/plugin.xml", self.data["demo_pkg/plugin.xml"].replace('path="demo_controller"', 'path="demo_pkg"'))
        self.change("demo_pkg/CMakeLists.txt", 'project("demo_pkg")\nadd_library("${PROJECT_NAME}" SHARED "src/controller.cpp")\npluginlib_export_plugin_description_file(controller_interface "plugin.xml")\n')
        self.assertEqual("fixture-controller", self.prepare()[0][0]["id"])

    def test_actual_cli_writes_a_fresh_register_compatible_draft(self):
        manifest_path, output = self.folder / "manifest.json", self.folder / "cli-drafts"
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        result = subprocess.run([sys.executable, "-s", "-B", str(ROOT / "tools/import_robot_plugins.py"), "--manifest", str(manifest_path),
                                 "--cache", str(self.cache), "--output-directory", str(output)], capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr.decode(errors="replace"))
        self.assertEqual("draft_metadata_written", json.loads(result.stdout)["status"])
        draft = json.loads((output / "fixture-controller.json").read_text(encoding="utf-8"))
        validate_skill(draft)
        self.assertEqual(self.plugin["id"], draft["id"])
        self.assertNotIn("evidence", draft)

    def test_comments_strings_and_raw_strings_cannot_supply_an_export(self):
        for fake in ["// " + EXPORT, "/* " + EXPORT + " */", 'const char *s = "' + EXPORT.strip() + '";', 'const char *s = R"tag("' + EXPORT + ')tag";']:
            with self.subTest(fake=fake):
                self.change("demo_pkg/src/controller.cpp", HEADER + fake)
                self.rejected("Exactly one")
        self.change("demo_pkg/src/controller.cpp", HEADER + 'const char *s = R"tag("' + EXPORT + ')tag";\n' + EXPORT)
        self.assertEqual(1, len(self.prepare()[0]))

    def test_conditional_duplicate_spliced_or_dynamic_exports_are_rejected(self):
        for source in ["#if 0\n" + EXPORT + "#endif\n", "#ifdef UNKNOWN_BUILD_FLAG\n" + EXPORT + "#endif\n", EXPORT + EXPORT,
                       "// ignored \\\n" + EXPORT, "// ignored \\ \r" + EXPORT, "void helper() {" + EXPORT + "}\n", EXPORT.replace("PLUGINLIB_EXPORT_CLASS", "PLUGINLIB_EXPORT_\\\nCLASS"), EXPORT.replace("demo::Controller", "SELECTED_TYPE()")]:
            with self.subTest(source=source):
                self.change("demo_pkg/src/controller.cpp", HEADER + source)
                self.rejected("Conditional|Exactly one|splices|differs")

    def test_cpp_and_xml_class_base_and_library_must_agree(self):
        original = self.data["demo_pkg/plugin.xml"]
        for value in [original.replace("demo::Controller", "demo::Other"), original.replace("controller_interface::ControllerInterface", "controller_interface::Other"), original.replace('path="demo_controller"', 'path="wrong"'), original.replace("</library>", '<class name="demo/Controller" type="demo::Controller" base_class_type="controller_interface::ControllerInterface"/></library>')]:
            with self.subTest(value=value):
                self.change("demo_pkg/plugin.xml", value)
                self.rejected("XML|ambiguous")

    def test_xml_entities_are_rejected_before_resolution(self):
        original = self.data["demo_pkg/plugin.xml"]
        self.change("demo_pkg/plugin.xml", '<!DOCTYPE library [<!ENTITY ext SYSTEM "https://example.invalid/no-fetch">]>' + original)
        self.rejected("DTD/entity")
        self.change("demo_pkg/plugin.xml", original)
        self.change("demo_pkg/package.xml", '<!DOCTYPE package><package><name>demo_pkg</name></package>')
        self.rejected("DTD/entity")

    def test_cmake_wrong_dynamic_conditional_or_fake_registration_is_rejected(self):
        original = self.data["demo_pkg/CMakeLists.txt"]
        candidates = [original.replace("src/controller.cpp", "src/wrong.cpp"), original.replace("plugin.xml", "other.xml"), original.replace("SHARED src/controller.cpp", "SHARED ${SOURCES}"),
                      original.replace("add_library", "# add_library"), original.replace("add_library(demo_controller SHARED src/controller.cpp)", 'set(FAKE "add_library(demo_controller SHARED src/controller.cpp)")'),
                      original.replace("add_library(demo_controller SHARED src/controller.cpp)", "#[[ add_library(demo_controller SHARED src/controller.cpp) ]]"),
                      original.replace("add_library(demo_controller SHARED src/controller.cpp)", "if(OPTION)\nadd_library(demo_controller SHARED src/controller.cpp)\nendif()"),
                      original.replace("demo_controller SHARED", "${UNKNOWN} SHARED"), original.replace("project(demo_pkg)", "project(${PROJECT_NAME})"),
                      original.replace("project(demo_pkg)", "project(demo_pkg)\nset(PROJECT_NAME changed)"), original + "target_sources(demo_controller PRIVATE extra.cpp)\n"]
        candidates += [original + "project(${OTHER_PROJECT})\n", original + "pluginlib_export_plugin_description_file(controller_interface unreviewed.xml)\n",
                       original + "set(${VARIABLE_NAME} changed)\n", "function(add_library)\nendfunction()\n" + original,
                       original.replace("project(demo_pkg)", "project()"),
                       original + "set_target_properties(demo_controller PROPERTIES OUTPUT_NAME another_library)\n",
                       original + "set_target_properties(demo_controller PROPERTIES LIBRARY_OUTPUT_NAME_DEBUG renamed)\n",
                       original + "set_property(TARGET demo_controller PROPERTY PREFIX changed)\n",
                       original + "set_property(TARGET demo_controller PROPERTY SUFFIX .other)\n"]
        for text in candidates:
            with self.subTest(text=text):
                self.change("demo_pkg/CMakeLists.txt", text)
                self.rejected("Selected|selected|CMake|library|export|PROJECT_NAME|Dynamic|dynamic|source")

    def test_all_source_setup_and_license_files_require_exact_pins(self):
        original = dict(self.data)
        for path, text in original.items():
            with self.subTest(path=path):
                self.change(path, text + "\nchanged", repin=False)
                self.rejected("changed|digest")
                self.change(path, text)
        pin = self.project["files"]["LICENSE"]
        pin["git_blob_sha1"] = "0" * 40
        self.rejected("digest")

    def test_source_package_and_full_license_conflicts_fail_even_after_repin(self):
        for path, text in [("demo_pkg/src/controller.cpp", HEADER + "// SPDX-License-Identifier: Apache-2.0\n" + EXPORT),
                           ("demo_pkg/package.xml", self.data["demo_pkg/package.xml"].replace("<license>MIT</license>", "<license>Apache License 2.0</license>")),
                           ("LICENSE", MIT + "\nSPDX-License-Identifier: Apache-2.0\n")]:
            with self.subTest(path=path):
                old = self.data[path]
                self.change(path, text)
                self.rejected("license conflict|notice")
                self.change(path, old)
        self.plugin["license"]["source_notice_quotes"].append("Unobserved additional permission")
        self.rejected("notice")

    def test_package_dependencies_and_reviewed_attribution_are_not_invented(self):
        self.plugin["reviewed_metadata"]["requirements"]["packages"].remove("pluginlib")
        self.rejected("requirements omit")
        self.plugin["reviewed_metadata"]["requirements"]["packages"].append("pluginlib")
        self.plugin["reviewed_metadata"]["authors"] = ["Unrelated copyright holder"]
        self.rejected("provenance")

    def test_explicit_pinned_package_author_credit_is_distinct_from_source_notice(self):
        self.plugin["reviewed_metadata"]["authors"].append("Package Author")
        self.plugin["author_provenance"]["Package Author"] = {"kind": "package_author", "path": "demo_pkg/package.xml", "name": "Package Author"}
        original = self.data["demo_pkg/package.xml"]
        self.change("demo_pkg/package.xml", original.replace("</package>", "<author>Package Author</author></package>"))
        self.assertEqual(["Fixture Robotics", "Package Author"], self.prepare()[0][0]["source"]["authors"])
        self.change("demo_pkg/package.xml", original.replace("</package>", "<maintainer>Package Author</maintainer></package>"))
        self.rejected("package author node")
        self.change("demo_pkg/package.xml", original.replace("</package>", "<author>Different Package Author</author></package>"))
        self.rejected("package author node")
        self.plugin["author_provenance"]["Package Author"]["path"] = "different/package.xml"
        self.rejected("package author node")
        self.plugin["author_provenance"]["Package Author"]["kind"] = "package_maintainer"
        self.rejected("Unsupported author provenance")

    def test_check_preserves_existing_intake_but_draft_mode_rejects_it(self):
        record, path = self.owned()
        before = path.read_bytes()
        self.assertEqual(1, len(self.prepare(check=True)[0]))
        self.assertEqual(before, path.read_bytes())
        self.rejected("duplicate a canonical")
        path.write_bytes(before + b" ")
        with self.assertRaisesRegex(ValueError, "reviewed exact bytes"):
            self.prepare(check=True)

    def test_canonical_and_manifest_duplicate_source_identity_is_normalized(self):
        draft = self.prepare()[0][0]
        draft["id"] = "other-owned-id"
        draft["source"]["repository"] = "https://github.com/EXAMPLE/robot_plugins.git/"
        (self.root / "catalog/references.json").write_text(json.dumps({"records": [draft]}), encoding="utf-8")
        self.rejected("duplicate a canonical")
        (self.root / "catalog/references.json").write_text('{"records": []}', encoding="utf-8")
        other = copy.deepcopy(self.plugin)
        other["id"] = "other-new-id"
        self.project["plugins"].append(other)
        self.rejected("Duplicate manifest")

    def test_output_is_fresh_exclusive_and_outside_canonical_directories(self):
        drafts = self.prepare()[0]
        existing = self.folder / "existing"
        existing.mkdir()
        sentinel = existing / "keep.txt"
        sentinel.write_bytes(b"keep")
        for name in ("schemas", "api", "plugins", ".git", "brand", "tools", ".local"):
            (self.root / name).mkdir(exist_ok=True)
        for output in (existing, *[self.root / name / "new-drafts" for name in ("catalog", "tools", "schemas", "api", "plugins", ".git", "brand")]):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "fresh output"):
                importer.write_drafts(drafts, output, self.root)
        self.assertEqual(b"keep", sentinel.read_bytes())
        local_output = self.root / ".local/new-drafts"
        importer.write_drafts(drafts, local_output, self.root)
        self.assertTrue((local_output / "fixture-controller.json").is_file())
        self.project["files"]["../escape.cpp"] = self.project["files"]["LICENSE"]
        self.rejected("Unsafe")

    def test_real_manifest_preserves_two_existing_h13_intake_metadata_identities(self):
        manifest = importer.read_json(ROOT / "catalog/plugin-projects.json")
        self.assertEqual(1, len(manifest["projects"]))
        project = manifest["projects"][0]
        self.assertEqual(10, len(project["files"]))
        self.assertEqual("8ce934536c6404750fb8aafc0b62b7d365049143", project["commit"])
        self.assertEqual({"ros2-joint-trajectory-controller", "ros2-diff-drive-controller"}, {p["id"] for p in project["plugins"]})
        for plugin in project["plugins"]:
            path = ROOT / "catalog/intake" / (plugin["id"] + ".json")
            raw = path.read_bytes()
            record = json.loads(raw)
            self.assertEqual(importer.digest(raw), plugin["owned_intake_sha256"])
            self.assertEqual(record["source"]["sha256"], project["files"][plugin["source_path"]]["sha256"])
            self.assertEqual(record["requirements"], plugin["reviewed_metadata"]["requirements"])
            self.assertEqual(record["source"]["authors"], plugin["reviewed_metadata"]["authors"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertFalse(record["access"]["hub_prepare"])


if __name__ == "__main__":
    unittest.main()
