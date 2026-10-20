"""Search entrypoints must preserve actual inputs, evidence and escaping."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import build_catalog as builder
from sample_pages import publish

class SamplePagesTests(unittest.TestCase):
    def test_homepage_identifies_a_repository_for_agent_discovery(self):
        html=builder.home([],builder.DEFAULT_BASE)
        self.assertIn('Discover robotic skills for AI agents',html)
        self.assertIn('public repository',html)
        self.assertNotIn('marketplace',html.lower())

    def test_pages_keep_pinned_inputs_and_evidence_and_are_readable_without_javascript(self):
        record=json.loads((ROOT/'catalog/records/pythonrobotics-astar-planner.json').read_text())
        record=copy.deepcopy(record);record['name']='<script>bad</script>'
        with tempfile.TemporaryDirectory() as temp:
            urls=publish([record],temp,'https://example.test/hub','a'*40,builder.shell)
            folder=Path(temp)/'samples'/record['id']
            payload=json.loads((folder/'index.json').read_text())
            self.assertEqual(payload['example_input'],record['invocation']['inputs'])
            self.assertEqual(payload['evidence'],record['evidence'])
            self.assertEqual(payload['source_commit'],record['source']['commit'])
            self.assertFalse(payload['execution_performed'])
            html=(folder/'index.html').read_text()
            self.assertNotIn('<script',html);self.assertNotIn('<style',html)
            self.assertIn('&lt;script&gt;',html)
            self.assertIn('https://example.test/hub/samples/'+record['id']+'/',html)
            self.assertIn('curl -fsSL',html)
            self.assertIn('Example input',(folder/'index.md').read_text())
            self.assertEqual(len(urls),2)

if __name__=='__main__':unittest.main()
