"""TV3 behavioral tests. All data in this file is synthetic."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import pytest
from checks.access.checker import run_all_checks
from checks.access.common import CONTROLS, redact, result, validate_results
from checks.access.evaluator import evaluate_privileges,evaluate_superusers,evaluate_network,role_closures,resource_contains,IncompleteObservation
from checks.access.plan import build_plan
from checks.access.collector import SSHCollector,inventory_nodes,CollectionError
from checks.access.policy import load_yaml,policy_problem
from cis_lab.report import generate_html_report,summarize_results,write_json_results

NOW=datetime(2026,11,7,15,tzinfo=timezone.utc)

@pytest.fixture
def policy():
    p=load_yaml(Path(__file__).resolve().parents[3]/"policies/lab.yml")
    p.update(approved_by="FIXTURE approver",approved_at="2026-11-01T00:00:00Z",review_due="2026-12-01")
    return p

@pytest.fixture
def observation(policy):
    roles=[{k:copy.deepcopy(r[k]) for k in ("role","is_superuser","can_login","member_of")} for r in policy["access"]["approved_roles"]]
    permissions=[dict(g,role=r["role"]) for r in policy["access"]["approved_roles"] for g in r["permissions"]]
    return {"complete":True,"roles":roles,"permissions":permissions,"evidence":"FIXTURE synthetic role snapshot"}

@pytest.fixture
def network():
    return {"complete":True,"service_active":True,"config_loaded":True,"config":{"listen_address":"192.168.56.11","rpc_address":"192.168.56.11","storage_port":7000,"native_transport_port":9042},"sockets":[{"address":"192.168.56.11","port":7000},{"address":"192.168.56.11","port":9042}],"evidence":"FIXTURE synthetic sockets"}

def test_clean_roles(policy,observation):
    assert evaluate_privileges(observation,policy,NOW)[0]=="PASS"
    assert evaluate_superusers(observation,policy,NOW)[0]=="PASS"

def test_inherited_modify_detected(policy,observation):
    observation["permissions"].append({"role":"reader_role","permission":"MODIFY","resource":"data/table/cis_demo/items"})
    status,actual,*_=evaluate_privileges(observation,policy,NOW)
    assert status=="FAIL"
    assert any(v["role"]=="app_reader" and v.get("granted_to")=="reader_role" for v in actual["violations"])

def test_parent_grant_is_excessive(policy,observation):
    observation["permissions"][0]["resource"]="data/keyspace/cis_demo"
    assert evaluate_privileges(observation,policy,NOW)[0]=="FAIL"

def test_missing_required_inherited_permission_is_failure(policy,observation):
    observation['permissions']=[g for g in observation['permissions'] if g['role']!='reader_role']
    status,actual,*_=evaluate_privileges(observation,policy,NOW)
    assert status=='FAIL'
    assert any(v['kind']=='missing_permission' and v['role']=='app_reader' for v in actual['violations'])

@pytest.mark.parametrize("approved,observed,expected",[("data/all","data/table/ks/t",True),("data/keyspace/ks","data/table/ks/t",True),("data/table/ks/t","data/keyspace/ks",False),("data/keyspace/ks","data/table/other/t",False)])
def test_resource_hierarchy(approved,observed,expected):
    assert resource_contains(approved,observed) is expected

def test_inherited_superuser_detected(policy,observation):
    reader=next(r for r in observation["roles"] if r["role"]=="reader_role")
    reader["member_of"]=["lab_dba"]
    status,actual,*_=evaluate_superusers(observation,policy,NOW)
    assert status=="FAIL" and {"reader_role","app_reader"}<=set(actual["unauthorized"])

@pytest.mark.parametrize("mutation",["empty","incomplete","missing_parent","cycle","string_bool"])
def test_bad_role_observations_do_not_pass(observation,mutation):
    if mutation=="empty":observation["roles"]=[]
    elif mutation=="incomplete":observation["complete"]=False
    elif mutation=="missing_parent":observation["roles"][0]["member_of"]=["absent"]
    elif mutation=="cycle":observation["roles"][0]["member_of"]=[observation["roles"][0]["role"]]
    else:observation["roles"][0]["is_superuser"]="false"
    with pytest.raises(IncompleteObservation):role_closures(observation)

@pytest.mark.parametrize("field,value",[("approved_by",None),("approved_at","2030-01-01T00:00:00Z"),("review_due","2020-01-01")])
def test_policy_lifecycle(policy,observation,field,value):
    policy[field]=value
    assert evaluate_superusers(observation,policy,NOW)[0]=="NEEDS_REVIEW"

def test_missing_permission_policy(policy,observation):
    policy["access"]["approved_roles"][0].pop("permissions")
    assert evaluate_privileges(observation,policy,NOW)[0]=="NEEDS_REVIEW"

def test_missing_auth_policy_is_review(policy,observation):
    policy['auth']=None
    assert evaluate_superusers(observation,policy,NOW)[0]=='NEEDS_REVIEW'
    assert evaluate_privileges(observation,policy,NOW)[0]=='NEEDS_REVIEW'

def test_network_config_and_socket(policy,network):
    assert evaluate_network(network,policy,NOW)[0]=="PASS"
    network["sockets"][0]["address"]="0.0.0.0"
    assert evaluate_network(network,policy,NOW)[0]=="FAIL"

def test_config_not_reloaded(policy,network):
    network["config_loaded"]=False
    assert evaluate_network(network,policy,NOW)[0]=="NEEDS_REVIEW"

def test_interface_can_have_unused_ipv6_address(policy,network):
    network['config'].pop('listen_address');network['config']['listen_interface']='ens5'
    network['interfaces']={'ens5':['192.168.56.11','fe80::1']}
    assert evaluate_network(network,policy,NOW)[0]=='PASS'

def test_rpc_duplicate_bind_is_failure(policy,network):
    network['config']['rpc_interface']='ens5'
    assert evaluate_network(network,policy,NOW)[0]=='FAIL'

def test_duplicate_yaml_is_rejected(tmp_path):
    path=tmp_path/"p.yml";path.write_text("access: {}\naccess: {}\n")
    with pytest.raises(ValueError):load_yaml(path)

def test_missing_collector_is_error(policy):
    rows=run_all_checks("node",policy,now=NOW)
    assert [r["status"] for r in rows[:3]]==["ERROR"]*3
    assert [r["status"] for r in rows[3:]]==["NOT_IMPLEMENTED"]*2
    validate_results(rows)

def test_report_and_schema_for_all_owners(tmp_path):
    rows=[result(cid,"fixture","NOT_IMPLEMENTED",None,None,"FIXTURE not implemented",run_id="fixture-run",policy_ref="fixture-policy",evidence="FIXTURE simulated data") for cid in CONTROLS]
    generate_html_report(rows,tmp_path/"r.html");write_json_results(rows,tmp_path/"r.json")
    s=summarize_results(rows)
    assert s["represented_control_count"]==20 and s["conclusive_control_count"]==0
    assert "DỮ LIỆU FIXTURE" in (tmp_path/"r.html").read_text()

def test_partial_node_error_prevents_aggregate_pass():
    rows=[result("3.5",target,status,{}, {},"check",run_id="r",policy_ref="p",evidence="FIXTURE") for target,status in [("a","PASS"),("b","ERROR")]]
    s=summarize_results(rows)
    assert s["controls"]["3.5"]["aggregate_status"]=="ERROR"
    assert s["conclusive_control_count"]==0

def test_html_escapes_and_masks(tmp_path):
    row=result("3.8","<script>alert(1)</script>","FAIL",{"password":"SECRET_SHOULD_NOT_APPEAR"},None,"password=SECRET_SHOULD_NOT_APPEAR",run_id="r",policy_ref="p",evidence="FIXTURE <img src=x onerror=alert(1)>")
    generate_html_report([row],tmp_path/"r.html")
    text=(tmp_path/"r.html").read_text()
    assert "SECRET_SHOULD_NOT_APPEAR" not in text and "<img src=x" not in text and "<script>alert(1)" not in text

@pytest.mark.parametrize("field,value",[("control_id","2.8"),("duration_ms",-1),("duration_ms",True),("duration_ms",float('nan')),("owner","TV1"),("cis_status","A"),("scope","node"),("timestamp_utc","garbage"),("timestamp_utc","2026-11-07T00:00Z")])
def test_invalid_contract_rejected(field,value):
    row=result("3.8","node","PASS",{}, {},"ok",run_id="r",policy_ref="p",evidence="FIXTURE")
    row[field]=value
    with pytest.raises(Exception):validate_results([row])

def test_plan_proposals_are_non_executable(policy,observation):
    observation["permissions"].append({"role":"reader_role","permission":"MODIFY","resource":"data/table/cis_demo/items"})
    rows=run_all_checks("node",policy,snapshot={"roles":observation},now=NOW)
    plan=build_plan(rows,b"policy")
    assert plan["executable"] is False and plan["approval_required"] is True
    actions=[a for a in plan["actions"] if a["action"]=="REVIEW_REVOKE_PERMISSION"]
    assert len(actions)==1 and actions[0]["role"]=="reader_role"

def test_duplicate_results_rejected(policy,observation,network):
    rows=run_all_checks("node",policy,snapshot={"roles":observation,"network":network},now=NOW)
    with pytest.raises(ValueError):validate_results(rows+[rows[0]])

def test_reports_do_not_merge_different_runs():
    rows=[result('3.8','cluster','PASS',{}, {},'ok',run_id=run,policy_ref='p',evidence='FIXTURE') for run in ['one','two']]
    with pytest.raises(ValueError):summarize_results(rows)

def test_collector_sends_secret_only_through_stdin(monkeypatch):
    from types import SimpleNamespace
    def fake_run(args,**kwargs):
        assert 'PRIVATE_SENTINEL' not in ' '.join(args)
        assert json.loads(kwargs['input'])['password']=='PRIVATE_SENTINEL'
        return SimpleNamespace(returncode=0,stdout=json.dumps({'ok':True,'observation':{'complete':True,'password':'PRIVATE_SENTINEL'}}))
    monkeypatch.setattr('checks.access.collector.subprocess.run',fake_run)
    c=SSHCollector({'all':{'children':{'cassandra_nodes':{'hosts':{'node':{'ansible_host':'192.0.2.1'}}}}}},'ssh.conf',credentials={'username':'audit','password':'PRIVATE_SENTINEL'})
    assert c.collect('node','roles')['password']=='***'

def test_unsafe_ssh_alias_is_rejected():
    with pytest.raises(ValueError):inventory_nodes({'all':{'children':{'cassandra_nodes':{'hosts':{'node;bad':{'ansible_host':'192.0.2.1'}}}}}})

def test_empty_report_is_not_full_coverage(tmp_path):
    assert summarize_results([])['conclusive_control_count']==0
    generate_html_report([],tmp_path/'empty.html')

def test_original_entrypoint_can_use_external_runtime(monkeypatch,policy,observation,network):
    class Collector:
        def collect(self,target,kind):return observation if kind=='roles' else network
    monkeypatch.setenv('CIS_LAB_ACCESS_RUNTIME','runtime.json')
    monkeypatch.setattr('checks.access.collector.collector_from_runtime_file',lambda path:Collector())
    rows=run_all_checks('node',policy,now=NOW)
    assert [r['status'] for r in rows[:3]]==['PASS']*3

def test_plan_state_fingerprint_ignores_run_timing():
    row=result('3.8','cluster','FAIL',{'unauthorized':['rogue_admin']},{'approved_superusers':['lab_dba']},'violation',run_id='one',policy_ref='p',evidence='FIXTURE')
    other=copy.deepcopy(row);other.update(run_id='two',duration_ms=999,timestamp_utc='2026-11-08T00:00:00Z')
    first,second=build_plan([row]),build_plan([other])
    assert first['observation_sha256']==second['observation_sha256']
    assert first['source_results_sha256']!=second['source_results_sha256']
    assert first['targets']==['cluster'] and first['impact']
