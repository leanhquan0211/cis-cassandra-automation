"""TV3 standalone entrypoint, leaving TV1's main runner untouched."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from .checker import run_all_checks
from .collector import SSHCollector, inventory_nodes
from .common import redact, result, validate_results
from .evaluator import evaluate_network
from .plan import build_plan
from .policy import load_yaml
from cis_lab.report import generate_html_report, generate_pdf_report, summarize_results, write_json_results

def audit(args):
    policy = load_yaml(args.policy)
    inventory = load_yaml(args.inventory)
    nodes = inventory_nodes(inventory)
    credentials = {}
    if args.credentials_file:
        path = Path(args.credentials_file)
        if path.stat().st_mode & 0o077:
            raise ValueError("Credentials file must have mode 0600 or stricter")
        credentials = json.loads(path.read_text())
    collector = SSHCollector(inventory,args.ssh_config,credentials=credentials,timeout=args.timeout)
    first = args.cluster_endpoint or next(iter(nodes))
    if first not in nodes:
        raise ValueError("Cluster endpoint must be in inventory")
    cluster = inventory.get("all",{}).get("vars",{}).get("cluster_name","inventory-cluster")
    run_id = args.run_id or "tv3-"+uuid.uuid4().hex
    out = Path(args.out)
    if (out/"results.json").exists():
        raise ValueError("Output run already exists; choose a new run directory")
    rows = run_all_checks(first,policy,collector=collector,run_id=run_id,policy_ref=args.policy)
    for row in rows:
        if row["scope"]=="cluster":
            row["target"]=cluster
    for target in nodes:
        if target==first:
            continue
        start=time.perf_counter()
        try:
            observation=collector.collect(target,"network")
            status,actual,expected,reason=evaluate_network(observation,policy)
            evidence=observation["evidence"]
        except Exception as error:
            status,actual,expected,reason="ERROR",None,None,"Network collection failed ("+type(error).__name__+")"
            evidence="No compliance conclusion; SSH/probe failed for "+target
        rows.append(result("3.5",target,status,actual,expected,reason,run_id=run_id,
            policy_ref=args.policy,evidence=evidence,duration_ms=(time.perf_counter()-start)*1000))
    evidence_dir=out/"evidence"; evidence_dir.mkdir(parents=True,exist_ok=True)
    for (target,kind),observation in collector.cache.items():
        path=evidence_dir/(target+"-"+kind+".json")
        path.write_text(json.dumps(redact(observation),ensure_ascii=False,indent=2)+"\n")
        for row in rows:
            matching=(row["control_id"] in ("3.3","3.8") and kind=="roles" and target==first) or (row["control_id"]=="3.5" and kind=="network" and row["target"]==target)
            if matching:
                row["evidence"]="evidence/"+path.name+"; "+row["evidence"]
    write_json_results(rows,out/"results.json")
    generate_html_report(rows,out/"report.html")
    generate_pdf_report(rows,out/"report.pdf",source_path=out/"results.json")
    (out/"summary.json").write_text(json.dumps(summarize_results(rows),indent=2)+"\n")
    plan=build_plan(rows,Path(args.policy).read_bytes())
    raw=(json.dumps(plan,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    (out/"plan.json").write_bytes(raw)
    (out/"plan.sha256").write_text(hashlib.sha256(raw).hexdigest()+"\n")
    print(json.dumps({"run_id":run_id,"out":str(out),"report_pdf":str(out/"report.pdf"),"statuses":summarize_results(rows)["status_counts"]},ensure_ascii=False))
    return 2 if any(row["status"]=="ERROR" for row in rows) else 0

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description="TV3 midterm audit/report/plan; no apply or CQL writes")
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("audit")
    a.add_argument("--inventory",required=True);a.add_argument("--policy",required=True)
    a.add_argument("--ssh-config",required=True);a.add_argument("--credentials-file")
    a.add_argument("--cluster-endpoint");a.add_argument("--out",required=True)
    a.add_argument("--run-id");a.add_argument("--timeout",type=int,default=75)
    for command in ("report","plan"):
        q=sub.add_parser(command);q.add_argument("--out",required=True)
        if command=="plan":
            q.add_argument("--input",required=True);q.add_argument("--policy",required=True)
        else:
            source=q.add_mutually_exclusive_group(required=True)
            source.add_argument("--input");source.add_argument("--matrix")
    args=p.parse_args()
    try:
        if args.command=="audit":return audit(args)
        if args.command=="report" and args.matrix:
            import re
            from .pdf_report import generate_comparison_pdf
            if Path(args.out).suffix.lower()!=".pdf":raise ValueError("Comparison output must be PDF")
            matrix_path=Path(args.matrix)
            matrix=json.loads(matrix_path.read_text())
            cases={}
            for case in matrix["matrix"]:
                name=case["scenario"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+",name) or name in cases:raise ValueError("Invalid scenario")
                rows=json.loads((matrix_path.parent/name/"results.json").read_text())
                counts=summarize_results(rows)["status_counts"]
                if any(counts[status]!=case.get(status,0) for status in counts):raise ValueError("Matrix/results count mismatch")
                cases[name]=rows
            if not cases:raise ValueError("No comparison cases")
            generate_comparison_pdf(cases,args.out,source_path=matrix_path)
            return 0
        rows=json.loads(Path(args.input).read_text());validate_results(rows)
        if args.command=="report":
            suffix=Path(args.out).suffix.lower()
            if suffix==".pdf":generate_pdf_report(rows,args.out,source_path=args.input)
            elif suffix in (".html",".htm"):generate_html_report(rows,args.out)
            else:raise ValueError("Report output must end in .pdf or .html")
        else:
            Path(args.out).write_text(json.dumps(build_plan(rows,Path(args.policy).read_bytes()),indent=2)+"\n")
        return 0
    except Exception as error:
        print("TV3 execution error: "+type(error).__name__+"; check configuration and input contracts",file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
