import importlib.util,pathlib,unittest,io,json,urllib.error
from unittest import mock
PATH=pathlib.Path(__file__).resolve().parents[2]/'tools/agent_reuse_pilot/judge.py'
spec=importlib.util.spec_from_file_location('pilot_judge',PATH);judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)
rspec=importlib.util.spec_from_file_location('pilot_runner',PATH.with_name('run.py'));runner=importlib.util.module_from_spec(rspec);rspec.loader.exec_module(runner)
class PilotJudgeTests(unittest.TestCase):
    def setUp(self):self.task={'start':[1,1],'goal':[3,1],'bounds':[0,5],'obstacles':[],'robot_radius':.3}
    def test_continuous_segment_collision(self):
        output={'path_xy':[[1,1],[3,1]],'length_m':2}
        self.assertTrue(judge.grade('astar',self.task,output)['passed'])
        self.task['obstacles']=[[2,1]]
        self.assertFalse(judge.grade('astar',self.task,output)['passed'])
    def test_reverse_and_false_length(self):
        self.assertFalse(judge.grade('astar',self.task,{'path_xy':[[3,1],[1,1]],'length_m':2})['passed'])
        self.assertFalse(judge.grade('astar',self.task,{'path_xy':[[1,1],[3,1]],'length_m':0})['passed'])
    def test_fabricated_and_nonfinite(self):
        self.assertFalse(judge.grade('astar',self.task,{'success':True})['passed'])
        self.assertFalse(judge.grade('astar',self.task,{'path_xy':[[1,1],[3,1]],'length_m':float('nan')})['passed'])
    def test_trajectory_cannot_teleport(self):
        task={'current_position':[0],'current_velocity':[0],'current_acceleration':[0],'target_position':[1],
              'target_velocity':[0],'target_acceleration':[0],'max_velocity':[1],'max_acceleration':[2],'max_jerk':[4],'dt':.02,'coordinate_type':'revolute_rad'}
        out={'time_s':[0,.02],'position':[[0],[1]],'velocity':[[0],[0]],'acceleration':[[0],[0]],'duration_s':.02,'coordinate_type':'revolute_rad'}
        result=judge.grade('trajectory',task,out)
        self.assertFalse(result['passed']);self.assertFalse(result['checks']['position_velocity_consistency'])
    def test_recoverable_lookup_error_is_model_feedback(self):
        error=urllib.error.HTTPError('https://api.superfastrobotics.com/v1/start',400,'Bad Request',{},io.BytesIO(json.dumps({'reason_code':'invalid_task_query','message':'Narrow query'}).encode()))
        with mock.patch.object(runner,'request',side_effect=error):
            result=runner.lookup({'source_hub_commit':'a'*40,'tasks':[]},'too many terms')
        self.assertEqual(result['http_status'],400);self.assertEqual(result['reason_code'],'invalid_task_query')
    def test_server_failure_is_not_a_bad_agent_query(self):
        error=urllib.error.HTTPError('https://api.superfastrobotics.com/v1/start',503,'Unavailable',{},io.BytesIO(b'{}'))
        with mock.patch.object(runner,'request',side_effect=error),self.assertRaises(urllib.error.HTTPError):
            runner.lookup({'source_hub_commit':'a'*40,'tasks':[]},'astar')
if __name__=='__main__':unittest.main()
