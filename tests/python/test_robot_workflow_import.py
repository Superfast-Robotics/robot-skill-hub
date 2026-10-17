"""Workflow pin, attribution and additive ownership checks; no upstream runtime."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_robot_workflows as importer


class RobotWorkflowImportTests(unittest.TestCase):
    def fixture(self):
        files = {"scripts/train.py": b"raise RuntimeError('source must never execute')\nif __name__ == '__main__':\n    main()\n",
                 "LICENSE": b"MIT License\nCopyright Example Robotics\nPermission is hereby granted, free of charge\n",
                 "README.md": b"# Setup\nExample Robotics team\nPython 3.12\n"}

        def pin(path):
            return {"path": path, "sha256": importer.examples.digest(files[path]), "bytes": len(files[path])}

        artifact = {**pin("scripts/train.py"), "entrypoint_kind": "python_main", "role": "policy-training",
                    "name": "Policy training", "summary": "Train a configured policy.", "capabilities": ["policy-training"],
                    "robot_types": ["source-defined"], "robot_scope": "The selected task determines compatibility."}
        project = {"id": "fixture", "name": "Example Robotics", "repository": "https://github.com/example/robot",
                   "commit": "1" * 40, "ref": "main", "stars": 0, "checked_at": "2026-10-18",
                   "authors": ["Example Robotics team"], "capabilities": ["policy-training"], "execution_domain": "computation",
                   "requirements": {"python": "3.12", "packages": [], "environment": "Configured task and dataset"},
                   "setup_url": "https://github.com/example/robot/blob/" + "1" * 40 + "/README.md",
                   "invocation_notes": "Requires upstream configuration.", "selection": {"include": ["scripts/train.py"]},
                   "license": {**pin("LICENSE"), "spdx": "MIT", "scope": "Selected workflow source only"},
                   "evidence_files": [{**pin("README.md"), "purpose": "author and setup", "contains": ["Example Robotics team", "Python 3.12"]}],
                   "artifacts": [artifact]}
        return {"schema_version": "1", "projects": [project]}, files

    def populate(self, cache, project, files):
        for path, data in files.items():
            target = importer.examples.cache_path(cache, project, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def test_offline_build_verifies_pins_without_executing_or_network(self):
        manifest, files = self.fixture()
        project = manifest["projects"][0]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.populate(cache, project, files)
            with mock.patch.object(importer.urllib.request, "urlopen", side_effect=AssertionError("offline")):
                record = importer.build(manifest, cache, {"records": []})["records"][0]
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual(["Example Robotics team"], record["source"]["authors"])
            self.assertEqual(len(files["LICENSE"]), record["license"]["bytes"])
            self.assertEqual("workflow", record["artifact"]["kind"])
            self.assertEqual(project["evidence_files"][0]["sha256"], record["access"]["setup_evidence"][0]["sha256"])
            self.assertEqual({"records": [record], "workflow_manifest": "workflow-projects.json"},
                             importer.build(manifest, cache, {"records": [record]}))

    def test_new_bounded_workflow_role_is_metadata_without_compatibility_inference(self):
        manifest, files = self.fixture()
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact["role"] = "underwater-inspection"
        build_fixture = RobotWorkflowExtensionTests().build_fixture
        record = build_fixture(manifest, files)
        self.assertEqual("underwater-inspection", record["artifact"]["workflow_role"])
        self.assertFalse(record["access"]["hub_prepare"])
        self.assertNotIn("compatibility", record)
        for role in ("", "Aerial-control", "camera/control", "x" * 81, "flight--control", "control\nrun"):
            artifact["role"] = role
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "workflow role"):
                build_fixture(manifest, files)

    def test_tampered_source_license_or_author_setup_document_is_rejected(self):
        for path in ["scripts/train.py", "LICENSE", "README.md"]:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                manifest, files = self.fixture()
                cache = Path(directory)
                project = manifest["projects"][0]
                self.populate(cache, project, files)
                importer.examples.cache_path(cache, project, path).write_bytes(files[path] + b"changed")
                with self.assertRaisesRegex(ValueError, "checksum/size"):
                    importer.build(manifest, cache, {"records": []})

    def test_library_source_and_different_per_file_license_are_rejected(self):
        for source in [b"def main():\n    pass\n", b"# SPDX-License-Identifier: GPL-3.0-only\nif __name__ == '__main__':\n    main()\n"]:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                manifest, files = self.fixture()
                project = manifest["projects"][0]
                files["scripts/train.py"] = source
                project["artifacts"][0].update(sha256=importer.examples.digest(source), bytes=len(source))
                cache = Path(directory)
                self.populate(cache, project, files)
                with self.assertRaises(ValueError):
                    importer.build(manifest, cache, {"records": []})

    def test_missing_byte_pin_and_missing_attribution_anchor_are_rejected(self):
        manifest, files = self.fixture()
        project = manifest["projects"][0]
        bad = copy.deepcopy(project)
        bad["license"]["bytes"] = 0
        with self.assertRaisesRegex(ValueError, "byte size"):
            importer.validate_project(bad)
        project["evidence_files"][0]["contains"] = ["Unsubstantiated author"]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.populate(cache, project, files)
            with self.assertRaisesRegex(ValueError, "anchor missing"):
                importer.build(manifest, cache, {"records": []})

    def test_merge_preserves_foreign_records_and_rejects_shared_immutable_source(self):
        foreign = {"id": "existing", "framework": "intake", "source_registry": "community-intake-v1",
                   "source": {"repository": "https://github.com/example/robot", "commit": "1" * 40, "path": "client.py"},
                   "evidence": {"runtime_verification": "not_run"}}
        original = copy.deepcopy(foreign)
        new = {**copy.deepcopy(foreign), "id": "new", "source_registry": importer.REGISTRY,
               "source": {**foreign["source"], "path": "server.py"}}
        merged = importer.merge_records([foreign], [new])
        self.assertEqual(original, next(record for record in merged if record["id"] == "existing"))
        duplicate = {**copy.deepcopy(new), "source": copy.deepcopy(foreign["source"])}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            importer.merge_records([foreign], [duplicate])

    def test_reviewed_manifest_is_unique_and_does_not_duplicate_other_registries(self):
        manifest = json.loads((ROOT / "catalog/workflow-projects.json").read_text(encoding="utf-8"))
        source_pins = []
        for project in manifest["projects"]:
            importer.validate_project(project)
            source_pins.extend((project["repository"], project["commit"], artifact["path"]) for artifact in project["artifacts"])
        self.assertEqual(len(source_pins), len(set(source_pins)))
        published = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        foreign = {(r["source"]["repository"], r["source"].get("commit"), r["source"]["path"])
                   for r in published if r.get("source_registry") != importer.REGISTRY}
        self.assertFalse(set(source_pins) & foreign)


class RobotWorkflowExtensionTests(unittest.TestCase):
    def nonstandard_project_license(self, manifest, files):
        text = b"Fixture SDK License (FIXTURE-2026)\nVendor product conditions apply.\n"
        files["LICENSE"] = text
        manifest["projects"][0]["license"] = {"path": "LICENSE", "sha256": importer.examples.digest(text),
            "bytes": len(text), "spdx": "LicenseRef-Fixture-FIXTURE-2026", "scope": "Source links under vendor terms.",
            "verified": False, "review_status": "nonstandard_upstream_terms",
            "source_terms": {"identifier": "FIXTURE-2026", "marker": "Fixture SDK License", "notes": "Vendor conditions apply."}}

    def test_nonstandard_project_terms_survive_console_entrypoint(self):
        manifest, files = self.console_fixture()
        self.nonstandard_project_license(manifest, files)
        record = self.build_fixture(manifest, files)
        self.assertEqual("python_console_script", record["evidence"]["entrypoint_kind"])
        self.assertEqual("LicenseRef-Fixture-FIXTURE-2026", record["license"]["spdx"])
        self.assertFalse(record["license"]["verified"])
        self.assertEqual("FIXTURE-2026", record["license"]["source_terms"]["identifier"])
        self.assertEqual("nonstandard_upstream_terms", record["license"]["review_status"])
        self.assertFalse(record["access"]["hub_prepare"])

    def test_scoped_file_notice_does_not_clear_nonstandard_project_terms(self):
        manifest, files = RobotWorkflowImportTests().fixture()
        self.nonstandard_project_license(manifest, files)
        notice = b"MIT License\nPermission is hereby granted, free of charge\n"
        files["THIRD_PARTY_LICENSE"] = notice
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact["license_review"] = {"spdx": "MIT", "verified": True, "review_status": "source_notice_reviewed",
            "scope": "Selected file's separate declaration; project terms remain separate.",
            "declarations": [{"spdx": "MIT", "path": "THIRD_PARTY_LICENSE", "sha256": importer.examples.digest(notice),
                              "bytes": len(notice), "scope": "Pinned separate file notice.",
                              "contains": ["Permission is hereby granted"]}]}
        record = self.build_fixture(manifest, files)
        self.assertEqual("MIT", record["license"]["spdx"])
        self.assertFalse(record["license"]["verified"])
        self.assertEqual("FIXTURE-2026", record["license"]["source_terms"]["identifier"])
        self.assertEqual("LicenseRef-Fixture-FIXTURE-2026", record["license"]["upstream_project_license"]["spdx"])
        self.assertFalse(record["license"]["upstream_project_license"]["verified"])

    def console_fixture(self, mixed=False):
        manifest, files = RobotWorkflowImportTests().fixture()
        project = manifest["projects"][0]
        source = (b"# Licensed under the Apache License, Version 2.0\n# MIT License\n"
                  b"# Permission is hereby granted, free of charge\n" if mixed else b"")
        source += b"raise RuntimeError('never import this source')\ndef main():\n    pass\n"
        setup = (b"from setuptools import setup\nraise RuntimeError('never execute setup')\n"
                 b"setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n")
        files.pop("scripts/train.py")
        files.update({"package/pkg/nomad.py": source, "package/setup.py": setup})
        artifact = project["artifacts"][0]
        artifact.update(path="package/pkg/nomad.py", sha256=importer.examples.digest(source), bytes=len(source),
                        entrypoint_kind="python_console_script", entrypoint="nomad",
                        console_script={"path": "package/setup.py", "sha256": importer.examples.digest(setup), "bytes": len(setup),
                                        "format": "setuptools_literal_console_scripts", "name": "nomad", "module": "pkg.nomad",
                                        "function": "main", "package_root": "package"})
        project["selection"]["include"] = [artifact["path"]]
        if mixed:
            pin = {key: artifact[key] for key in ("path", "sha256", "bytes")}
            artifact["license_review"] = {"spdx": "NOASSERTION", "verified": False, "scope": "Source link only; mixed scopes unresolved.",
                "review_status": "mixed_source_notices_unresolved", "declarations": [
                    {**pin, "spdx": "Apache-2.0", "scope": "First-party header", "contains": ["# Licensed under the Apache License"]},
                    {**pin, "spdx": "MIT", "scope": "Incorporated-code notice", "contains": ["# MIT License"]}]}
        return manifest, files

    def build_fixture(self, manifest, files):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            RobotWorkflowImportTests().populate(cache, manifest["projects"][0], files)
            with mock.patch.object(importer.urllib.request, "urlopen", side_effect=AssertionError("offline only")):
                return importer.build(manifest, cache, {"records": []})["records"][0]

    def test_console_registration_is_static_and_never_imports_source_or_setup(self):
        manifest, files = self.console_fixture()
        record = self.build_fixture(manifest, files)
        self.assertEqual("python_console_script", record["evidence"]["entrypoint_kind"])
        self.assertEqual("pkg.nomad:main", record["evidence"]["console_registration"]["target"])
        self.assertEqual("not_run", record["evidence"]["runtime_verification"])
        self.assertFalse(record["access"]["hub_prepare"])

    def test_dynamic_registration_is_not_evaluated(self):
        manifest, files = self.console_fixture()
        setup = b"from setuptools import setup\nENTRIES = {'console_scripts': ['nomad = pkg.nomad:main']}\nsetup(entry_points=ENTRIES)\n"
        files["package/setup.py"] = setup
        manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "literal setuptools"):
            self.build_fixture(manifest, files)

    def test_console_target_path_and_function_must_both_match(self):
        manifest, files = self.console_fixture()
        manifest["projects"][0]["artifacts"][0]["console_script"]["module"] = "other.nomad"
        with self.assertRaisesRegex(ValueError, "module path"):
            self.build_fixture(manifest, files)
        manifest, files = self.console_fixture()
        setup = files["package/setup.py"].replace(b":main", b":missing")
        files["package/setup.py"] = setup
        manifest["projects"][0]["artifacts"][0]["console_script"].update(function="missing", sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "top-level source function"):
            self.build_fixture(manifest, files)

    def test_duplicate_console_command_name_with_other_target_is_ambiguous(self):
        manifest, files = self.console_fixture()
        setup = (b"from setuptools import setup\nsetup(entry_points={'console_scripts': "
                 b"['nomad = pkg.nomad:main', 'nomad = other:evil']})\n")
        files["package/setup.py"] = setup
        manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.build_fixture(manifest, files)

    def test_literal_and_dynamic_console_list_elements_are_rejected(self):
        manifest, files = self.console_fixture()
        setup = (b"from setuptools import setup\nsetup(entry_points={'console_scripts': "
                 b"['nomad = pkg.nomad:main', make_registration()]})\n")
        files["package/setup.py"] = setup
        manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "literal string"):
            self.build_fixture(manifest, files)

    def test_setup_alias_rebinding_and_deletion_are_rejected_without_execution(self):
        mutations = [
            "setup = lambda **kwargs: None",
            "setup: object = None",
            "setup += replacement",
            "del setup",
            "import other as setup",
            "from other import setup",
            "def setup(**kwargs):\n    pass",
            "class setup:\n    pass",
            "for setup in []:\n    pass",
            "with resource() as setup:\n    pass",
            "try:\n    pass\nexcept Exception as setup:\n    pass",
            "(setup := replacement)",
            "match value:\n    case {'setup': setup}:\n        pass",
        ]
        for mutation in mutations:
            manifest, files = self.console_fixture()
            setup = ("from setuptools import setup\n" + mutation
                     + "\nsetup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n").encode()
            files["package/setup.py"] = setup
            manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "binding.*ambiguous"):
                self.build_fixture(manifest, files)

    def test_target_function_rebinding_and_deletion_are_rejected(self):
        mutations = [
            "main = 42", "main: object = 42", "main += replacement", "del main",
            "import other as main", "from other import main",
            "def main():\n    pass", "class main:\n    pass",
            "for main in []:\n    pass", "(main := replacement)",
            "match value:\n    case {'target': main}:\n        pass",
            "def other(value=(main := 42)):\n    pass",
            "class Other:\n    global main\n    main = 42",
        ]
        for mutation in mutations:
            manifest, files = self.console_fixture()
            source = ("def main():\n    pass\n" + mutation + "\n").encode()
            files["package/pkg/nomad.py"] = source
            manifest["projects"][0]["artifacts"][0].update(sha256=importer.examples.digest(source), bytes=len(source))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "binding.*ambiguous"):
                self.build_fixture(manifest, files)

    def test_module_alias_mutation_and_dynamic_binding_forms_are_outside_subset(self):
        setups = [
            "import setuptools as st\nst.setup = replacement\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "import setuptools as st\ndel st.setup\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "import setuptools as st\nst.__dict__.update(setup=replacement)\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "from setuptools import setup\nfrom other import *\nsetup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "from setuptools import setup\nglobals()['setup'] = replacement\nsetup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "import builtins\nimport setuptools as st\nbuiltins.setattr(st, 'setup', replacement)\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "from builtins import setattr as mutate\nimport setuptools as st\nmutate(st, 'setup', replacement)\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
        ]
        for text in setups:
            manifest, files = self.console_fixture()
            setup = text.encode()
            files["package/setup.py"] = setup
            manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
            with self.subTest(setup=text), self.assertRaisesRegex(ValueError, "binding|literal subset"):
                self.build_fixture(manifest, files)
        for text in ["def main():\n    pass\nglobals()['main'] = 42\n",
                     "def main():\n    pass\nmain.__dict__['replacement'] = 42\n",
                     "@replacement\ndef main():\n    pass\n"]:
            manifest, files = self.console_fixture()
            source = text.encode()
            files["package/pkg/nomad.py"] = source
            manifest["projects"][0]["artifacts"][0].update(sha256=importer.examples.digest(source), bytes=len(source))
            with self.subTest(source=text), self.assertRaisesRegex(ValueError, "binding|literal subset"):
                self.build_fixture(manifest, files)

    def test_function_bodies_and_class_local_names_do_not_rebind_module(self):
        manifest, files = self.console_fixture()
        setup = (b"from setuptools import setup\ndef local(setup):\n    setup = None\n"
                 b"class Local:\n    setup = None\n"
                 b"setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n")
        source = (b"def main():\n    model.eval()\n    vars(model)\n"
                  b"class Local:\n    main = 42\n    def method(self, main):\n        main = None\n")
        files.update({"package/setup.py": setup, "package/pkg/nomad.py": source})
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact.update(sha256=importer.examples.digest(source), bytes=len(source))
        artifact["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        self.assertEqual("pkg.nomad:main", self.build_fixture(manifest, files)["evidence"]["console_registration"]["target"])

    def test_unique_literal_setup_alias_must_precede_call(self):
        for text in [
            "from setuptools import setup as build\nbuild(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
            "import setuptools as st\nst.setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n",
        ]:
            manifest, files = self.console_fixture()
            setup = text.encode()
            files["package/setup.py"] = setup
            manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
            with self.subTest(setup=text):
                self.assertEqual("pkg.nomad:main", self.build_fixture(manifest, files)["evidence"]["console_registration"]["target"])
        manifest, files = self.console_fixture()
        source = b"def main():\n    model.eval()\n"
        files["package/pkg/nomad.py"] = source
        manifest["projects"][0]["artifacts"][0].update(sha256=importer.examples.digest(source), bytes=len(source))
        self.assertEqual("pkg.nomad:main", self.build_fixture(manifest, files)["evidence"]["console_registration"]["target"])
        manifest, files = self.console_fixture()
        setup = b"setup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\nfrom setuptools import setup\n"
        files["package/setup.py"] = setup
        manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "imported before"):
            self.build_fixture(manifest, files)
        files["package/setup.py"] = setup = b"from .setuptools import setup\nsetup(entry_points={'console_scripts': ['nomad = pkg.nomad:main']})\n"
        manifest["projects"][0]["artifacts"][0]["console_script"].update(sha256=importer.examples.digest(setup), bytes=len(setup))
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.build_fixture(manifest, files)

    def test_console_setup_and_license_notice_bytes_are_pinned(self):
        for path in ("package/setup.py", "package/pkg/nomad.py"):
            manifest, files = self.console_fixture(mixed=True)
            files[path] += b"# changed\n"
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "checksum/size"):
                self.build_fixture(manifest, files)

    def test_mixed_notices_remain_unresolved_and_cannot_be_cleared(self):
        manifest, files = self.console_fixture(mixed=True)
        record = self.build_fixture(manifest, files)
        self.assertEqual("NOASSERTION", record["license"]["spdx"])
        self.assertFalse(record["license"]["verified"])
        self.assertEqual(["Apache-2.0", "MIT"], [item["spdx"] for item in record["license"]["upstream_declarations"]])
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact["license_review"].update(spdx="Apache-2.0", verified=True)
        with self.assertRaisesRegex(ValueError, "Mixed license declarations"):
            self.build_fixture(manifest, files)
        manifest, files = self.console_fixture(mixed=True)
        manifest["projects"][0]["artifacts"][0].pop("license_review")
        with self.assertRaisesRegex(ValueError, "mixed source license"):
            self.build_fixture(manifest, files)

    def test_per_workflow_python_and_incomplete_paths_do_not_change_project_requirements(self):
        manifest, files = RobotWorkflowImportTests().fixture()
        original = copy.deepcopy(manifest)
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact.update(role="dataset-preparation", capabilities=["dataset-preparation"],
                        requirements={"python": ">=3.10,<3.12", "environment": "Separate data environment", "notes": "Declarations only"},
                        declared_requirements={"gpu": "unknown"},
                        limitations=["Selected data CLI only; trainer is unimplemented", "One extraction branch imports an absent module"])
        record = self.build_fixture(manifest, files)
        self.assertEqual(">=3.10,<3.12", record["requirements"]["python"])
        self.assertEqual("Separate data environment", record["requirements"]["display"])
        self.assertEqual("unknown", record["requirements"]["declared_requirements"]["gpu"])
        self.assertEqual(artifact["limitations"], record["evidence"]["limitations"])
        self.assertNotIn("policy-training", record["capabilities"])
        self.assertEqual(original["projects"][0]["requirements"], manifest["projects"][0]["requirements"])

    def test_reviewed_robot_names_filter_as_discovery_without_compatibility_combinations(self):
        sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
        from rshlib.core import reference_environment_matches
        manifest, files = RobotWorkflowImportTests().fixture()
        files["README.md"] += b"SO100 robot demonstration\n"
        project = manifest["projects"][0]
        pin = project["evidence_files"][0]
        pin.update(sha256=importer.examples.digest(files["README.md"]), bytes=len(files["README.md"]))
        project["artifacts"][0]["robot_discovery"] = {"labels": ["so100"], "scope": "Named example only; compatibility unknown.",
            "evidence": [{**{key: pin[key] for key in ("path", "sha256", "bytes")}, "quote": "SO100 robot demonstration", "labels": ["so100"]}]}
        record = self.build_fixture(manifest, files)
        self.assertTrue(reference_environment_matches(record, {"robot": "so100"}))
        self.assertFalse(reference_environment_matches(record, {"robot": "so101"}))
        self.assertFalse(reference_environment_matches(record, {"robot": "so100", "runtime": "fixture"}))
        self.assertNotIn("compatibility", record)
        self.assertFalse(record["evidence"]["robot_discovery"]["compatibility_inferred"])
        project["artifacts"][0]["robot_discovery"]["evidence"][0]["quote"] = "SO100 absent source quote"
        with self.assertRaisesRegex(ValueError, "quote is absent"):
            self.build_fixture(manifest, files)
        project["artifacts"][0].pop("robot_discovery")
        generic = self.build_fixture(manifest, files)
        self.assertNotIn("robots", generic)
        self.assertFalse(reference_environment_matches(generic, {"robot": "so100"}))

    def test_robot_label_requires_whole_words_and_accepts_sdk_namespace(self):
        manifest, files = RobotWorkflowImportTests().fixture()
        files["README.md"] += b"logging1\nfake_so100x\nfrom unitree_sdk2py.g1.loco import LocoClient\n"
        project = manifest["projects"][0]
        pin = project["evidence_files"][0]
        pin.update(sha256=importer.examples.digest(files["README.md"]), bytes=len(files["README.md"]))
        for label, quote in [("g1", "logging1"), ("so100", "fake_so100x")]:
            project["artifacts"][0]["robot_discovery"] = {"labels": [label], "scope": "Source name only; compatibility unknown.",
                "evidence": [{**{key: pin[key] for key in ("path", "sha256", "bytes")}, "quote": quote, "labels": [label]}]}
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "complete robot label"):
                self.build_fixture(manifest, files)
        project["artifacts"][0]["robot_discovery"] = {"labels": ["g1"], "scope": "SDK name only; compatibility unknown.",
            "evidence": [{**{key: pin[key] for key in ("path", "sha256", "bytes")}, "quote": "from unitree_sdk2py.g1.loco import LocoClient", "labels": ["g1"]}]}
        self.assertEqual(["g1"], self.build_fixture(manifest, files)["robots"])

    def test_source_path_discovery_is_limited_to_exact_selected_artifact(self):
        manifest, files = RobotWorkflowImportTests().fixture()
        source = files.pop("scripts/train.py")
        files["examples/g1/control.py"] = source
        project = manifest["projects"][0]
        artifact = project["artifacts"][0]
        artifact["path"] = "examples/g1/control.py"
        project["selection"]["include"] = [artifact["path"]]
        pin = {key: artifact[key] for key in ("path", "sha256", "bytes")}
        artifact["robot_discovery"] = {"labels": ["g1"], "scope": "Filename discovery only; runtime unknown.",
            "evidence": [{**pin, "quote": "examples/g1/", "labels": ["g1"], "match_in": "source_path"}]}
        record = self.build_fixture(manifest, files)
        self.assertEqual(["g1"], record["robots"])
        self.assertEqual("source_path", record["evidence"]["robot_discovery"]["evidence"][0]["match_in"])
        artifact["robot_discovery"]["evidence"][0].update({key: project["evidence_files"][0][key] for key in ("path", "sha256", "bytes")})
        with self.assertRaisesRegex(ValueError, "selected source itself"):
            self.build_fixture(manifest, files)

    def test_capability_keyword_requires_pinned_literal_text(self):
        manifest, files = RobotWorkflowImportTests().fixture()
        files["README.md"] += b"Policy server and inference\n"
        project = manifest["projects"][0]
        pin = project["evidence_files"][0]
        pin.update(sha256=importer.examples.digest(files["README.md"]), bytes=len(files["README.md"]))
        artifact = project["artifacts"][0]
        artifact["capabilities"].append("policy-inference")
        artifact["capability_evidence"] = [{**{key: pin[key] for key in ("path", "sha256", "bytes")}, "quote": "Policy server and inference", "capabilities": ["policy-inference"]}]
        self.assertIn("policy-inference", self.build_fixture(manifest, files)["capabilities"])
        artifact["capability_evidence"][0]["quote"] = "Policy inference not present"
        with self.assertRaisesRegex(ValueError, "Capability evidence quote is absent"):
            self.build_fixture(manifest, files)


class TopLevelSdkScriptTests(unittest.TestCase):
    def fixture(self, source=None):
        manifest, files = RobotWorkflowImportTests().fixture()
        if source is None:
            source = ("raise RuntimeError('source must never execute')\n"
                      "from fixture_sdk.wrapper import Robot as SDK\n"
                      "arm = SDK(address)\narm.move()\n")
        files["scripts/train.py"] = source.encode()
        artifact = manifest["projects"][0]["artifacts"][0]
        artifact.update(sha256=importer.examples.digest(files["scripts/train.py"]), bytes=len(files["scripts/train.py"]),
            entrypoint_kind="python_top_level_script", script_entrypoint={
                "format": "from_import_constructor_methods", "import_module": "fixture_sdk.wrapper",
                "import_name": "Robot", "import_binding": "SDK", "instance": "arm", "methods": ["move"]})
        return manifest, files

    def build_source(self, source=None):
        manifest, files = self.fixture(source)
        return RobotWorkflowExtensionTests().build_fixture(manifest, files)

    def test_reviewed_script_is_static_source_only_without_importing_or_network(self):
        record = self.build_source()
        evidence = record["evidence"]
        self.assertEqual("python_top_level_script", evidence["entrypoint_kind"])
        proof = evidence["script_entrypoint"]
        self.assertEqual("fixture_sdk.wrapper", proof["import_module"])
        self.assertEqual(3, proof["constructor_line"])
        self.assertEqual([{"method": "move", "line": 4}], proof["method_calls"])
        self.assertFalse(proof["reachability_verified"])
        self.assertFalse(proof["compatibility_inferred"])
        self.assertEqual("not_run", evidence["runtime_verification"])
        self.assertIn("syntactic evidence", evidence["inspection"])
        self.assertFalse(record["access"]["hub_prepare"])
        self.assertNotIn("compatibility", record)
        self.assertNotIn("robots", record)

    def test_module_if_try_and_loop_bodies_qualify_without_reachability_claims(self):
        bodies = ["if False:\n    arm.move()\n", "while unknown:\n    arm.move()\n",
                  "for item in unknown:\n    arm.move()\n", "try:\n    arm.move()\nexcept Exception:\n    pass\n"]
        for body in bodies:
            with self.subTest(body=body):
                record = self.build_source("from fixture_sdk.wrapper import Robot as SDK\narm = SDK(address)\n" + body)
                self.assertEqual("move", record["evidence"]["script_entrypoint"]["method_calls"][0]["method"])
                self.assertFalse(record["evidence"]["script_entrypoint"]["reachability_verified"])

    def test_constructor_only_and_deferred_or_spoofed_calls_do_not_qualify(self):
        bodies = ["", "print('arm.move()')\n# arm.move()\n", "other.move()\n", "arm.stop()\n",
                  "def helper():\n    arm.move()\n", "async def helper():\n    arm.move()\n",
                  "class Helper:\n    arm.move()\n", "callback = lambda: arm.move()\n",
                  "values = [arm.move() for item in items]\n", "values = {arm.move() for item in items}\n",
                  "values = {item: arm.move() for item in items}\n", "values = (arm.move() for item in items)\n"]
        for body in bodies:
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "Every reviewed SDK method"):
                self.build_source("from fixture_sdk.wrapper import Robot as SDK\narm = SDK(address)\n" + body)
        for source in ["from fixture_sdk.wrapper import Robot as SDK\narm.move()\narm = SDK(address)\n",
                       "from fixture_sdk.wrapper import Robot as SDK\narm = SDK(arm.move())\n"]:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "Every reviewed SDK method"):
                self.build_source(source)

    def test_exact_import_constructor_and_assignment_order_are_required(self):
        sources = ["import fixture_sdk.wrapper\narm = SDK(address)\narm.move()\n",
                   "from .fixture_sdk.wrapper import Robot as SDK\narm = SDK(address)\narm.move()\n",
                   "from other_sdk.wrapper import Robot as SDK\narm = SDK(address)\narm.move()\n",
                   "from fixture_sdk.wrapper import Other as SDK\narm = SDK(address)\narm.move()\n",
                   "from fixture_sdk.wrapper import Robot\narm = Robot(address)\narm.move()\n",
                   "arm = SDK(address)\nfrom fixture_sdk.wrapper import Robot as SDK\narm.move()\n",
                   "from fixture_sdk.wrapper import Robot as SDK\nif unknown:\n    arm = SDK(address)\narm.move()\n",
                   "from fixture_sdk.wrapper import Robot as SDK\narm = another = SDK(address)\narm.move()\n",
                   "from fixture_sdk.wrapper import Robot as SDK\narm: object = SDK(address)\narm.move()\n"]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.build_source(source)

    def test_rebound_deleted_or_mutated_sdk_bindings_are_rejected(self):
        mutations = ["SDK = replacement", "del SDK", "import other as SDK", "from other import SDK",
                     "arm = replacement", "arm: object = replacement", "del arm", "import other as arm",
                     "arm = SDK(address)", "arm.move = replacement", "del arm.move",
                     "arm.__dict__.update(move=replacement)", "SDK.__dict__.update(move=replacement)",
                     "globals()['arm'] = replacement", "setattr(arm, 'move', replacement)",
                     "for arm in []:\n    pass", "(arm := replacement)",
                     "def helper(value=(arm := replacement)):\n    pass"]
        for mutation in mutations:
            source = ("from fixture_sdk.wrapper import Robot as SDK\narm = SDK(address)\n"
                      + mutation + "\narm.move()\n")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.build_source(source)

    def test_descriptor_is_bounded_literal_data_and_all_methods_must_match(self):
        mutations = [{}, {"format": "eval"}, {"methods": []}, {"methods": ["move", "move"]},
                     {"methods": ["move()"]}, {"methods": ["move"] * 21}, {"methods": "move"},
                     {"import_module": ".fixture_sdk.wrapper"}, {"import_module": "x" * 201},
                     {"instance": "SDK"}, {"instance": "arm.value"}, {"unexpected": True}]
        for mutation in mutations:
            manifest, files = self.fixture()
            descriptor = manifest["projects"][0]["artifacts"][0]["script_entrypoint"]
            if mutation:
                descriptor.update(mutation)
            else:
                descriptor.clear()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "bounded literal SDK"):
                RobotWorkflowExtensionTests().build_fixture(manifest, files)
        manifest, files = self.fixture()
        manifest["projects"][0]["artifacts"][0]["script_entrypoint"]["methods"].append("stop")
        with self.assertRaisesRegex(ValueError, "Every reviewed SDK method"):
            RobotWorkflowExtensionTests().build_fixture(manifest, files)


if __name__ == "__main__":
    unittest.main()
