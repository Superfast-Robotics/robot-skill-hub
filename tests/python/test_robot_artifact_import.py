"""Source/configuration provenance and static-only ingestion checks."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_robot_artifacts as importer


class RobotArtifactImportTests(unittest.TestCase):
    def fixture(self):
        source = b'<robot name="fixture"><link name="base"/></robot>\n'
        license_text = b'MIT License\nPermission is hereby granted, free of charge\nTHE SOFTWARE IS PROVIDED\n'
        project = {
            "id": "fixture", "name": "Fixture descriptions", "repository": "https://github.com/example/robot", "commit": "1" * 40,
            "ref": "reviewed-label", "stars": 0, "checked_at": "2026-10-18", "robot_types": ["arm"],
            "capabilities": ["robot-description"], "packages": ["Upstream robot package"], "environment": "Not loaded", "execution_domain": "configuration",
            "setup_url": "https://github.com/example/robot/blob/" + "1" * 40 + "/README.md",
            "licenses": {"LICENSE": {"spdx": "MIT", "sha256": importer.digest(license_text), "scope": "Description text only; adjacent assets have separate rights."}},
            "artifacts": [{"path": "urdf/arm.urdf", "sha256": importer.digest(source), "bytes": len(source), "kind": "robot_description", "format": "urdf", "license_path": "LICENSE"}],
        }
        return project, source, license_text

    def cached(self, cache, project, source, license_text):
        for path, data in [(project["artifacts"][0]["path"], source), ("LICENSE", license_text)]:
            target = importer.cache_path(cache, project, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def test_exact_source_and_applicable_license_bytes_required(self):
        project, source, license_text = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.cached(cache, project, source, license_text)
            importer.validate_project(project)
            importer.checked_licenses(project, cache)
            record = importer.make_record(project, project["artifacts"][0], cache)
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertEqual("urdf", record["artifact"]["format"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertIn(project["commit"], record["source"]["url"])
            importer.cache_path(cache, project, "urdf/arm.urdf").write_bytes(source + b" ")
            with self.assertRaisesRegex(ValueError, "checksum/size"):
                importer.make_record(project, project["artifacts"][0], cache)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text + b" changed")
            with self.assertRaisesRegex(ValueError, "license checksum"):
                importer.checked_licenses(project, cache)

    def test_xml_is_parsed_without_resolving_adjacent_or_remote_files(self):
        source = b'<mujoco><include file="https://example.test/not-fetched.xml"/><asset><mesh file="../assets/mesh.stl"/></asset></mujoco>'
        with mock.patch.object(importer.urllib.request, "urlopen", side_effect=AssertionError("No network during static inspection")):
            result = importer.inspect_artifact("model/scene.xml", source)
        self.assertEqual("mjcf", result["format"])
        self.assertEqual(["../assets/mesh.stl", "https://example.test/not-fetched.xml"], result["references"])
        for data in [b'<!DOCTYPE robot [<!ENTITY x "a">]><robot name="&x;"/>', b'<html/>', b'<robot>', b'\x00binary', b'\xff']:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeDecodeError, importer.ET.ParseError)):
                importer.inspect_artifact("urdf/arm.urdf", data)

    def test_xacro_and_yaml_are_not_evaluated_or_claimed_semantically_valid(self):
        result = importer.inspect_artifact("robot.urdf.xacro", b'<robot xmlns:xacro="http://www.ros.org/wiki/xacro"><xacro:include filename="$(find package)/other.xacro"/></robot>')
        self.assertEqual("xacro", result["format"])
        self.assertIn("not evaluated", result["inspection"])
        yaml = importer.inspect_artifact("config/limits.yaml", b'joint_limits:\n  joint1:\n    max_velocity: 2.0\n')
        self.assertEqual(["joint1", "joint_limits", "max_velocity"], yaml["keys"])
        self.assertIn("semantics", yaml["inspection"])
        self.assertIn("not evaluated", yaml["inspection"])
        with self.assertRaisesRegex(ValueError, "mapping keys"):
            importer.inspect_artifact("config/limits.yaml", b'# comments only\n')

    def test_project_rejects_mutable_refs_unknown_licenses_and_unsafe_paths(self):
        project, *_ = self.fixture()
        for edit in [lambda p:p.update(commit="main"), lambda p:p["artifacts"][0].update(path="../escape.urdf"),
                     lambda p:p["licenses"]["LICENSE"].update(spdx="LicenseRef-Unreviewed"),
                     lambda p:p["artifacts"][0].update(license_path="elsewhere/LICENSE"),
                     lambda p:p["artifacts"][0].update(bytes=importer.MAX_BYTES+1)]:
            changed = copy.deepcopy(project)
            edit(changed)
            with self.assertRaises(ValueError):
                importer.validate_project(changed)

    def test_foreign_records_preserved_and_duplicates_fail_closed(self):
        foreign = {"id":"existing","framework":"robot","source":{"repository":"https://github.com/example/robot","commit":"1"*40,"path":"old.py"}}
        owned = {**copy.deepcopy(foreign), "id":"owned", "source_registry":importer.REGISTRY}
        replacement = {**copy.deepcopy(owned), "source":{**owned["source"],"path":"new.urdf"}}
        combined = importer.merge_records([foreign,owned],[replacement])
        self.assertEqual(foreign, next(r for r in combined if r["id"]=="existing"))
        self.assertEqual("new.urdf", next(r for r in combined if r["id"]=="owned")["source"]["path"])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            importer.merge_records([foreign],[copy.deepcopy(foreign)])

    def test_empty_or_duplicate_project_manifests_cannot_drop_owned_records(self):
        project, *_ = self.fixture()
        for manifest in [{"schema_version":"1","projects":[]}, {"schema_version":"2","projects":[project]},
                         {"schema_version":"1","projects":[project,copy.deepcopy(project)]}]:
            with self.assertRaisesRegex(ValueError,"nonempty versioned manifest"):
                importer.build(manifest,Path("unused"),{"records":[]})

    def test_long_ids_are_stable_bounded_and_do_not_collide(self):
        project, source, license_text = self.fixture()
        artifact=project["artifacts"][0]
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)
            ids=[]
            for suffix in ("one", "two"):
                artifact["path"]="urdf/"+"shared-long-path-"*10+suffix+".urdf"
                self.cached(cache,project,source,license_text)
                record=importer.make_record(project,artifact,cache)
                self.assertLessEqual(len(record["id"]),80)
                ids.append(record["id"])
            self.assertNotEqual(*ids)

    def test_explicit_file_license_cannot_override_the_reviewed_license(self):
        project, _, license_text=self.fixture()
        source=b'<!-- SPDX-License-Identifier: Apache-2.0 --><robot name="arm"/>'
        artifact=project["artifacts"][0]
        artifact.update(sha256=importer.digest(source),bytes=len(source))
        with tempfile.TemporaryDirectory() as directory:
            self.cached(Path(directory),project,source,license_text)
            with self.assertRaisesRegex(ValueError,"per-file license"):
                importer.make_record(project,artifact,Path(directory))

    def test_matching_xml_license_and_model_specific_setup_are_preserved(self):
        project, _, license_text = self.fixture()
        source = b'<!-- SPDX-License-Identifier: MIT --><robot name="arm"/>'
        artifact = project["artifacts"][0]
        artifact.update(sha256=importer.digest(source), bytes=len(source), setup_path="urdf/README.md")
        with tempfile.TemporaryDirectory() as directory:
            self.cached(Path(directory), project, source, license_text)
            record = importer.make_record(project, artifact, Path(directory))
        self.assertTrue(record["access"]["setup_url"].endswith("/" + project["commit"] + "/urdf/README.md"))

    def test_published_artifact_inventory_matches_its_applicable_license_pins(self):
        manifest = json.loads((ROOT / "catalog/artifact-projects.json").read_text(encoding="utf-8"))
        references = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        managed = {(r["source"]["repository"], r["source"]["commit"], r["source"]["path"]):r
                   for r in references if r.get("source_registry")==importer.REGISTRY}
        count = 0
        for project in manifest["projects"]:
            importer.validate_project(project)
            for artifact in project["artifacts"]:
                record = managed[project["repository"], project["commit"], artifact["path"]]
                license_info = project["licenses"][artifact["license_path"]]
                self.assertEqual(artifact["sha256"], record["source"]["sha256"])
                self.assertEqual(artifact["bytes"], record["source"]["bytes"])
                self.assertEqual(artifact["kind"], record["artifact"]["kind"])
                self.assertEqual(artifact["format"], record["artifact"]["format"])
                self.assertEqual(license_info["sha256"], record["license"]["sha256"])
                self.assertEqual(license_info["spdx"], record["license"]["spdx"])
                self.assertIn("/"+project["commit"]+"/"+artifact["license_path"], record["license"]["url"])
                self.assertEqual("not_run",record["evidence"]["runtime_verification"])
                self.assertFalse(record["access"]["hub_prepare"])
                count += 1
        self.assertEqual(len(managed), count)

    def bt_fixture(self):
        source = b'<root BTCPP_format="4" main_tree_to_execute="MainTree"><BehaviorTree ID="MainTree"><PipelineSequence><ComputePathToPose goal="{goal}" path="{path}"/><FollowPath path="{path}"/></PipelineSequence></BehaviorTree></root>'
        package = b'<package><name>fixture_package</name><license>Apache-2.0</license><maintainer>Package maintainer, not XML author</maintainer></package>'
        index = b'Package-specific licenses apply.\nFor files that are not otherwise marked, they are provided under the Apache-2.0\nlicense.\n'
        files = {'fixture_package/trees/nav.xml': source, 'LICENSE': index, 'other_package/LICENSE': b'Apache License\nVersion 2.0\nEND OF TERMS AND CONDITIONS\n',
                 'fixture_package/package.xml': package, 'fixture_package/CMakeLists.txt': b'install(DIRECTORY trees DESTINATION share/${PROJECT_NAME})\n',
                 'fixture_package/README.md': b'A configured upstream host loads the XML.\n'}
        def pin(path): return {'path':path,'sha256':importer.digest(files[path]),'bytes':len(files[path])}
        project, *_ = self.fixture()
        project['licenses'] = {'LICENSE': {'spdx':'Apache-2.0','sha256':importer.digest(index),'bytes':len(index),'scope':'Selected otherwise-unmarked XML only.',
             'binding':{'kind':'package_with_unmarked_file_fallback','package':pin('fixture_package/package.xml'),'package_name':'fixture_package',
                        'unmarked_file_quote':'For files that are not otherwise marked, they are provided under the Apache-2.0\nlicense.','terms':pin('other_package/LICENSE')}}}
        project['evidence_files'] = [{**pin('fixture_package/CMakeLists.txt'),'quotes':['install(DIRECTORY trees']}, {**pin('fixture_package/README.md'),'quotes':['configured upstream host']}]
        project['artifacts'] = [{**pin('fixture_package/trees/nav.xml'),'kind':'workflow','format':importer.BT_FORMAT,'license_path':'LICENSE','name':'Reviewed tree','summary':'Declares planning and following; not run.'}]
        return project, files

    def bt_build(self, project, files, fetch=False):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            if not fetch:
                for path, raw in files.items():
                    target = importer.cache_path(cache, project, path); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            return importer.build({'schema_version':'1','projects':[project]},cache,{'records':[]},fetch=fetch)['records'][0]

    def test_behavior_tree_is_a_literal_inventory_with_separate_grant_and_terms(self):
        project, files = self.bt_fixture()
        with mock.patch.object(importer.urllib.request,'urlopen',side_effect=AssertionError('No network for cached XML')):
            record = self.bt_build(project,files)
        structure = record['artifact']['structure']
        self.assertEqual(3,structure['node_count'])
        self.assertEqual(['{goal}','{path}'],structure['blackboard_references'])
        self.assertEqual({'tag':'FollowPath','attributes':{'path':'{path}'},'children':0},structure['nodes'][-1])
        self.assertTrue(record['license']['url'].endswith('/LICENSE'))
        self.assertEqual(importer.digest(files['LICENSE']),record['license']['sha256'])
        self.assertIn('/other_package/LICENSE',record['license']['binding']['terms']['url'])
        self.assertIn('terms text only',record['license']['binding']['terms']['scope'])
        self.assertNotIn('Package maintainer',json.dumps(record))
        self.assertNotIn('authors',record['source'])
        self.assertEqual('source_reference',record['access']['mode'])
        self.assertFalse(record['access']['hub_prepare'])
        self.assertEqual('not_run',record['evidence']['runtime_verification'])
        self.assertIsNone(record['requirements']['python'])
        self.assertNotIn('compatibility',record)

    def test_behavior_tree_rejects_unsupported_graphs_namespaces_and_external_input(self):
        project, files = self.bt_fixture(); source = files[project['artifacts'][0]['path']]
        invalid = [source.replace(b'BTCPP_format="4"',b'BTCPP_format="3"'), source.replace(b'ID="MainTree"',b'ID="Other"'),
                   source.replace(b'<BehaviorTree',b'<root/><BehaviorTree',1), source.replace(b'</BehaviorTree>',b'<Wait/></BehaviorTree>'),
                   source.replace(b'<FollowPath path="{path}"/>',b'<SubTree ID="Elsewhere"/>'), source.replace(b'<FollowPath path="{path}"/>',b'<include path="https://invalid.test/tree.xml"/>'),
                   source.replace(b'<FollowPath path="{path}"/>',b'<TreeNodesModel/>'), source.replace(b'<FollowPath',b'<x:FollowPath xmlns:x="urn:foreign"'),
                   source.replace(b'path="{path}"/>',b'x:path="{path}" xmlns:x="urn:foreign"/>'), source.replace(b'<root ',b'<root xmlns="urn:foreign" ',1),
                   b'<!DOCTYPE root [<!ENTITY ext SYSTEM "https://invalid.test/data">]>'+source,
                   source.replace(b'main_tree_to_execute="MainTree"',b'main_tree_to_execute="{dynamic}"'), source.replace(b'<PipelineSequence>',b'<PipelineSequence>not attribute data',1)]
        with mock.patch.object(importer.urllib.request,'urlopen',side_effect=AssertionError('External data must not be fetched')):
            for raw in invalid:
                with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                    importer.inspect_artifact('tree.xml',raw)

    def test_behavior_tree_resource_bounds_cover_depth_nodes_and_output_bytes(self):
        wrap = lambda body: b'<root BTCPP_format="4" main_tree_to_execute="MainTree"><BehaviorTree ID="MainTree">'+body+b'</BehaviorTree></root>'
        cases = [b'<Sequence>'*65+b'<Wait/>'+b'</Sequence>'*65,
                 b'<Sequence>'+b'<Wait/>'*importer.BT_MAX_NODES+b'</Sequence>',
                 b'<Sequence>'+b'<Wait value="'+b'a'*1000+b'"/>' + (b'<Wait value="'+b'a'*1000+b'"/>')*40+b'</Sequence>']
        for body in cases:
            with self.subTest(bytes=len(body)), self.assertRaises(ValueError): importer.inspect_artifact('tree.xml',wrap(body))

    def test_behavior_tree_kind_and_format_cannot_be_mispaired(self):
        project, _ = self.bt_fixture()
        for key,value in [('kind','robot_description'),('format','urdf'),('path','fixture_package/tree.yaml')]:
            changed=copy.deepcopy(project);changed['artifacts'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): importer.validate_project(changed)

    def test_package_fallback_requires_package_rule_and_terms_not_just_a_license_marker(self):
        project,files=self.bt_fixture()
        for mode in ('missing_rule','wrong_package_license','duplicate_package_license','duplicate_package_name','sibling_prefix','late_file_notice','wrong_terms'):
            p,f=copy.deepcopy(project),copy.deepcopy(files);binding=p['licenses']['LICENSE']['binding']
            if mode=='missing_rule':
                f['LICENSE']=b'Apache License Version 2.0; no fallback grant.';p['licenses']['LICENSE'].update(sha256=importer.digest(f['LICENSE']),bytes=len(f['LICENSE']))
            elif mode in ('wrong_package_license','duplicate_package_license','duplicate_package_name'):
                path=binding['package']['path'];f[path]=f[path].replace(b'<license>Apache-2.0</license>',b'<license>MIT</license>' if mode=='wrong_package_license' else b'<license>Apache-2.0</license><license>MIT</license>') if mode!='duplicate_package_name' else f[path].replace(b'</package>',b'<name>other_package</name></package>')
                binding['package'].update(sha256=importer.digest(f[path]),bytes=len(f[path]))
            elif mode=='sibling_prefix':
                artifact=p['artifacts'][0];raw=f.pop(artifact['path']);artifact['path']='fixture_package_other/trees/nav.xml';f[artifact['path']]=raw
            elif mode=='late_file_notice':
                artifact=p['artifacts'][0];f[artifact['path']]+=b' '*6500+b'<!-- SPDX-License-Identifier: MIT -->';artifact.update(sha256=importer.digest(f[artifact['path']]),bytes=len(f[artifact['path']]))
            else:
                path=binding['terms']['path'];f[path]=b'No full Apache terms';binding['terms'].update(sha256=importer.digest(f[path]),bytes=len(f[path]))
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.bt_build(p,f)

    def test_all_support_bytes_and_reviewed_anchors_are_required(self):
        project,files=self.bt_fixture()
        for path in ('fixture_package/package.xml','fixture_package/CMakeLists.txt','fixture_package/README.md','other_package/LICENSE'):
            changed=copy.deepcopy(files);changed[path]+=b' changed'
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'checksum/size'):self.bt_build(project,changed)
        p,f=copy.deepcopy(project),copy.deepcopy(files);pin=p['evidence_files'][1];f[pin['path']]=b'No approved setup statement';pin.update(sha256=importer.digest(f[pin['path']]),bytes=len(f[pin['path']]))
        with self.assertRaisesRegex(ValueError,'anchor'):self.bt_build(p,f)

    def test_explicit_fetch_collects_all_fixed_support_paths_without_discovery(self):
        project,files=self.bt_fixture();requested=[]
        def response(request,timeout):
            path=request.full_url.split(project['commit']+'/',1)[1];requested.append(path);return io.BytesIO(files[path])
        with mock.patch.object(importer.urllib.request,'urlopen',side_effect=response):record=self.bt_build(project,files,fetch=True)
        self.assertEqual(set(files),set(requested));self.assertEqual(len(files),len(requested))
        self.assertEqual('not_run',record['evidence']['runtime_verification'])

    def test_pinned_nav2_inventory_preserves_literal_discrepancies_and_unknown_runtime(self):
        manifest=json.loads((ROOT/'catalog/artifact-projects.json').read_text(encoding='utf-8'))
        project=next(p for p in manifest['projects'] if p['id']=='nav2')
        refs=json.loads((ROOT/'catalog/references.json').read_text(encoding='utf-8'))['records']
        selected={r['source']['path']:r for r in refs if r.get('source_registry')==importer.REGISTRY and r['framework']=='nav2'}
        self.assertEqual(12,len(selected));self.assertEqual(12,len(project['artifacts']))
        self.assertEqual('58e4019eb149ed4387938d9cd13f38659b86f754',project['commit'])
        for record in selected.values():
            self.assertFalse(record['access']['hub_prepare']);self.assertEqual('not_run',record['evidence']['runtime_verification']);self.assertIsNone(record['requirements']['python'])
            self.assertTrue(record['license']['url'].endswith('/LICENSE'));self.assertEqual('nav2_bt_navigator',record['license']['binding']['package']['name'])
        through=next(r for p,r in selected.items() if p.endswith('/navigate_through_poses_w_replanning_and_recovery.xml'))
        self.assertEqual(['0.333'],[n['attributes']['hz'] for n in through['artifact']['structure']['nodes'] if n['tag']=='RateController'])
        pose=next(r for p,r in selected.items() if p.endswith('/navigate_to_pose_w_replanning_and_recovery.xml'))
        self.assertEqual(['{backup_code_id}'],[n['attributes']['error_code_id'] for n in pose['artifact']['structure']['nodes'] if n['tag']=='BackUp'])


if __name__ == "__main__":
    unittest.main()
