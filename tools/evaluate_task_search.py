"""One offline opt-in task batch against immutable H15 authored cases.

Controls retain all_terms. This is a Python matcher measurement, not adoption,
robot execution, API traffic or a claim about a later live catalog generation.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import traceback
import evaluate_search as baseline

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--build-receipt', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    assert ROOT in output.parents and not output.exists()
    output.mkdir(parents=True, exist_ok=False)
    calls, blocked = 0, []
    save, read, sha = baseline.save, baseline.read, baseline.sha
    try:
        suite, cases_raw = read(ROOT / 'benchmarks/search/tasks.h15.json')
        assert sha(cases_raw) == '4baf7f22e35411325da2535fadf9248f5bad472310b8ac71ec0263b2423a6186'
        receipt, receipt_raw = read(args.build_receipt)
        assert sha(receipt_raw) == suite['publisher_receipt_sha256'] and receipt['head'] == suite['fixture_generation'] and receipt['tree'] == suite['fixture_tree'] and receipt['counts'] == suite['counts'] and receipt['builder_exit_code'] == 0
        version, raw = read(args.site / 'catalog/v1/version.json')
        assert version['hub_commit'] == suite['fixture_generation'] and version['counts'] == suite['counts']
        resources = {'catalog/v1/version.json': {'bytes': len(raw), 'sha256': sha(raw)}}

        def resource(name, path):
            value, raw = read(args.site / path)
            assert value['hub_commit'] == suite['fixture_generation'] and sha(raw) == version['resources'][name]['sha256']
            resources[path] = {'bytes': len(raw), 'sha256': sha(raw)}
            return value

        catalog = resource('index', 'catalog/v1/index.json')
        references = resource('references', 'catalog/v1/references.json')
        manifest = resource('search-manifest', 'catalog/v2/search-manifest.json')
        compact = {}
        for page in manifest['pages']:
            assert baseline.safe(page['path']) and page['bytes'] <= 256 * 1024
            value, raw = read(args.site / page['path'])
            assert len(raw) == page['bytes'] and sha(raw) == page['sha256'] and len(value['records']) == page['records'] and value['hub_commit'] == suite['fixture_generation']
            resources[page['path']] = {'bytes': len(raw), 'sha256': sha(raw)}
            for row in value['records']:
                assert row['id'] not in compact
                compact[row['id']] = row
        records = {r['id']: (r, False) for r in catalog['records']}
        for r in references['records']:
            assert r['id'] not in records
            records[r['id']] = (r, True)
        assert len(records) == len(compact) == manifest['records'] == 1303
        for identifier, target in suite['targets'].items():
            record, reference = records[identifier]
            assert sha(baseline.canonical(record)) == target['record_json_sha256'] and record['license'] == target['license']
            assert (record['source'].get('commit') or record['source'].get('revision')) == target['source_commit']
            assert ('source-' + record['source']['sha256'] if reference else record['maintenance']['record_version']) == target['record_version']
        catalog.update(references=references, catalog_origin='complete_local_publisher_fixture', references_origin='complete_local_publisher_fixture', discovery_scope='complete_offline_inventory', coverage={'complete': True})
        references['coverage'] = {'complete': True}

        def audit(event, _args):
            if event in {'socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo', 'socket.gethostbyname', 'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec'}:
                blocked.append(event)
                raise RuntimeError('Offline evaluation denied: ' + event)
        sys.addaudithook(audit)
        sys.path.insert(0, str(ROOT / 'skills/find-robot-skills/scripts'))
        from rshlib import core, task_search
        core.validate_catalog(catalog)
        # Full records and actual publisher compact rows must feed identical
        # scoring fields; no builder modification or synthetic source labels.
        projection_mismatches = [identifier for identifier, (record, _) in records.items()
                                 if task_search.fields(record) != task_search.fields(compact[identifier])]
        assert not projection_mismatches, projection_mismatches[:10]
        dependencies = {p: sha((ROOT / p).read_bytes()) for p in (
            'tools/evaluate_task_search.py', 'tools/evaluate_search.py',
            'skills/find-robot-skills/scripts/rshlib/core.py',
            'skills/find-robot-skills/scripts/rshlib/task_search.py',
            'benchmarks/search/task-lexical-v1.json', 'benchmarks/search/task-candidate-scope-v2.json')}
        assert dependencies['benchmarks/search/task-lexical-v1.json'] == task_search.SPEC_SHA256
        assert dependencies['benchmarks/search/task-candidate-scope-v2.json'] == task_search.CANDIDATE_SPEC_SHA256
        save(output / 'request.json', {'at': datetime.now(timezone.utc).isoformat(), 'cases_sha256': sha(cases_raw), 'dependencies': dependencies, 'fixture_generation': suite['fixture_generation'], 'fixture_tree': suite['fixture_tree'], 'publisher_receipt_sha256': sha(receipt_raw), 'resources': resources, 'plan': '40 task-mode cases plus20 unchanged strict controls; fixed coefficients, no tuning', 'all_full_compact_field_projections_equal': len(records)})
        rows, raw_results = [], []
        for case in suite['cases']:
            assert calls < 60
            calls += 1
            is_task = case['group'] == 'task'
            mode = 'task' if is_task else 'all_terms'
            item = {'id': case['id'], 'group': case['group'], 'query': case['query'], 'query_mode': mode, 'environment': case['environment']}
            try:
                result = core.find(catalog, case['query'], case['environment'], limit=10, hub_commit=case.get('hub_commit', suite['fixture_generation']), query_mode=mode)
            except core.RshError as error:
                raw_results.append({'id': case['id'], 'error': error.result})
                item.update(actual_error=error.result['reason_code'], returned_ids=[], total_matches=None)
                if not is_task:
                    item['control_pass'] = case.get('expected_error') == error.result['reason_code']
                result, ids = None, []
            else:
                raw_results.append({'id': case['id'], 'response': result})
                assert result['execution_performed'] is False and result['catalog_hub_commit'] == result['references_hub_commit'] == suite['fixture_generation']
                assert result['search_semantics'] == (task_search.VERSION if is_task else 'all_terms_word_prefix')
                ids = [r['id'] for r in result['results']]
                for row in result['results']:
                    record, reference = records[row['id']]
                    assert row['source_commit'] == (record['source'].get('commit') or record['source'].get('revision'))
                    assert row['memory_base'] == {'source_commit': row['source_commit'], 'hub_commit': suite['fixture_generation'], 'record_version': 'source-' + record['source']['sha256'] if reference else record['maintenance']['record_version']}
                    assert row['hub_prepare'] is (not reference)
                    assert not reference or row['compatibility_status'] == 'unknown'
                item.update(returned_ids=ids, total_matches=result['total'], source_version_identity_preserved=True,
                            **({key: result[key] for key in ('query_terms', 'candidate_count', 'candidate_scope', 'candidate_limit')} if is_task else {}))
            if is_task:
                expected = set(case['expected_ids'])
                ranks = [ids.index(identifier) + 1 for identifier in expected if identifier in ids]
                item.update(task_id=case['task_id'], variant=case['variant'], expected_ids=case['expected_ids'], first_labeled_rank_at_10=min(ranks) if ranks else None,
                    hit_at_1=int(bool(expected.intersection(ids[:1]))), hit_at_3=int(bool(expected.intersection(ids[:3]))), hit_at_10=int(bool(ranks)),
                    labeled_recall_at_3=len(expected.intersection(ids[:3])) / len(expected), labeled_recall_at_10=len(expected.intersection(ids)) / len(expected), reciprocal_rank_at_10=1 / min(ranks) if ranks else 0)
            elif result is not None:
                checks = []
                if 'expected_first' in case: checks.append(bool(ids) and ids[0] == case['expected_first'])
                if 'expected_total' in case: checks.append(result['total'] == case['expected_total'])
                if 'expected_ids_exact' in case: checks.append(set(ids) == set(case['expected_ids_exact']) and result['total'] == len(case['expected_ids_exact']))
                if 'required_ids' in case: checks.append(set(case['required_ids']).issubset(ids))
                if 'expected_terms' in case: checks.append(core.query_terms(case['query']) == case['expected_terms'])
                if 'compatibility_status' in case: checks.append(bool(ids) and all(r['compatibility_status'] == case['compatibility_status'] for r in result['results']))
                if 'expected_error' in case: checks.append(False)
                assert checks
                item['control_pass'] = all(checks)
                if case['id'] == 'full-eight-field-recipe':
                    # The separate original adjudication explains the old label
                    # error. Original labels/results are never rewritten.
                    item['adjudicated_control_pass'] = bool(ids) and ids[0] == 'maniskill-xarm6-pick-cube' and 'maniskill-xarm6-pick-cube' in ids and all(core.compatibility(records[r['id']][0], case['environment'])['compatibility_status'] == 'documented' for r in result['results'])
            rows.append(item)
        assert calls == 60 and not blocked
        with (output / 'raw-matcher-results.jsonl').open('x', encoding='utf-8') as stream:
            for row in raw_results: stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        save(output / 'case-results.json', rows)
        tasks, controls = [r for r in rows if r['group'] == 'task'], [r for r in rows if r['group'] == 'control']
        result = {'status': 'OFFLINE_TASK_MODE_MEASURED_FIXED_SPEC', 'at': datetime.now(timezone.utc).isoformat(), 'dependencies': dependencies,
            'cases_sha256': sha(cases_raw), 'fixture_generation': suite['fixture_generation'], 'fixture_tree': suite['fixture_tree'], 'counts': suite['counts'],
            'matcher_calls': calls, 'task_mode_calls': 40, 'strict_control_calls': 20, 'all_full_compact_field_projections_equal': len(records),
            'metrics': {'all_task_queries': baseline.summary(tasks), 'short': baseline.summary([r for r in tasks if r['variant'] == 'short']), 'natural': baseline.summary([r for r in tasks if r['variant'] == 'natural'])},
            'controls': {'total': len(controls), 'original_label_passed': sum(r['control_pass'] for r in controls), 'original_label_failed_ids': [r['id'] for r in controls if not r['control_pass']], 'separate_adjudicated_passed': sum(r.get('adjudicated_control_pass', r['control_pass']) for r in controls)},
            'task_error_cases': [r['id'] for r in tasks if r.get('actual_error')], 'network_or_subprocess_attempts': blocked,
            'bounds': {'robot_or_upstream_execution': False, 'CLI_processes': 0, 'API_requests': 0, 'native_index_runs': 0, 'models_or_embeddings': 0},
            'caveats': ['Maintainer-authored engineering cases; no external user/agent adoption measured.', 'Selected relevance labels are incomplete; no exhaustive recall or precision claim.', 'Historical baseline remains unchanged. Task mode is explicit; controls use unchanged all_terms.', 'H15 complete retained fixture1303 records, not a later live catalog generation.', 'Whole-catalog unfiltered task mode can reject >512 hard-filtered records; narrowing text alone does not reduce scope.', 'Only Python ranking is measured here; protocol/native agreement belongs to separate contract tests.'],
            'case_results_sha256': sha((output / 'case-results.json').read_bytes()), 'raw_results_sha256': sha((output / 'raw-matcher-results.jsonl').read_bytes())}
        save(output / 'result.json', result)
        print(json.dumps({'status': result['status'], 'metrics': result['metrics'], 'controls': result['controls'], 'task_error_cases': result['task_error_cases']}))
    except BaseException as error:
        save(output / 'failure.json', {'status': 'FAILED_STOP_NO_RETRY', 'error_type': type(error).__name__, 'message': str(error)[:500], 'matcher_calls': calls, 'traceback': traceback.format_exc()})
        raise


if __name__ == '__main__':
    main()
