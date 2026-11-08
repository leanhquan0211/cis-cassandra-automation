"""
cis_lab.report
Owner: TV3 (Đoàn Văn Tài)
Role: Tổng hợp dữ liệu kết quả đánh giá, tính toán độ bao phủ (coverage),
      và xuất báo cáo định dạng report.html và results.json.
"""

from collections import Counter
from html import escape
import json
from pathlib import Path
from checks.access.common import CONTROLS, STATUSES, redact, validate_results


def summarize_results(results):
    rows = validate_results(results)
    if len({r["run_id"] for r in rows}) > 1:
        raise ValueError("Report expects one run; do not merge observations from different runs")
    by_control = {}
    priority = ["ERROR", "FAIL", "NEEDS_REVIEW", "NOT_IMPLEMENTED", "PASS", "NOT_APPLICABLE"]
    for control in CONTROLS:
        group = [r for r in rows if r["control_id"] == control]
        statuses = {r["status"] for r in group}
        aggregate = next((s for s in priority if s in statuses), "NO_RESULT")
        by_control[control] = {"aggregate_status": aggregate, "result_count":len(group), "targets":sorted({r["target"] for r in group})}
    counts = Counter(r["status"] for r in rows)
    conclusive = [k for k,v in by_control.items() if v["aggregate_status"] in ("PASS","FAIL")]
    return {"benchmark_control_count":20,"result_count":len(rows),
        "status_counts":{s:counts[s] for s in STATUSES},
        "represented_control_count":sum(v["result_count"]>0 for v in by_control.values()),
        "conclusive_control_count":len(conclusive),"conclusive_coverage_percent":len(conclusive)*100/20,
        "missing_controls":[k for k,v in by_control.items() if not v["result_count"]],
        "controls":by_control}


def write_json_results(results, output_path):
    safe = redact(validate_results(results))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe,ensure_ascii=False,indent=2,allow_nan=False)+"\n")


def generate_html_report(results, output_path):
    """Offline report for all owners; missing controls and partial node errors stay visible."""
    rows = redact(validate_results(results))
    summary = summarize_results(rows)
    def text(value):
        return escape(str(value), quote=True)
    def pretty(value):
        return text(json.dumps(value,ensure_ascii=False,indent=2))
    coverage = "".join(f'<tr><td>{text(cid)}</td><td>{text(CONTROLS[cid][0])}</td><td>{text(item["aggregate_status"])}</td><td>{item["result_count"]}</td></tr>' for cid,item in summary["controls"].items())
    detail = "".join(
        f'<article data-status="{text(row["status"])}"><h3>{text(row["control_id"])} · {text(row["target"])} · {text(row["status"])}</h3>'
        f'<p>{text(row["reason"])}</p><p>Owner: {text(row["owner"])}; CIS: {text(row["cis_status"])}; scope: {text(row["scope"])}; {row["duration_ms"]:.3f} ms</p>'
        f'<details><summary>Actual / expected / evidence</summary><pre>{pretty(row["actual"])}</pre><pre>{pretty(row["expected"])}</pre><pre>{text(row["evidence"])}</pre></details></article>' for row in rows)
    fixture = any("FIXTURE" in r["evidence"].upper() or "SIMULATED" in r["evidence"].upper() for r in rows)
    document = f'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CIS Cassandra report</title><style>body{{font:16px system-ui;max-width:1150px;margin:auto;padding:24px;color:#172d40;background:#f5f8fb}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:8px;border:1px solid #ccd8e2;text-align:left}}article{{padding:14px;margin:14px 0;background:white;border-left:5px solid #31789b}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}select{{padding:8px}}</style>
<h1>CIS Cassandra Security Report</h1><p>Người thực hiện: Doan Van Tai</p>
<p>{'DỮ LIỆU FIXTURE — không phải kết quả node thật' if fixture else 'Nguồn và giới hạn quan sát được ghi tại evidence của từng kết quả.'}</p>
<p>Run: {text(rows[0]['run_id']) if rows else 'No results'} · Kết quả: {len(rows)} · Control có kết luận PASS/FAIL: {summary['conclusive_control_count']}/20 ({summary['conclusive_coverage_percent']:.1f}%). Đây không phải chứng nhận CIS.</p>
<pre>{pretty(summary['status_counts'])}</pre><h2>Coverage theo mã duy nhất</h2><p>NO_RESULT: chưa có kết quả được cung cấp; không suy ra đã triển khai hay đã đạt. Mỗi control chỉ được tính một lần. Lỗi trên một node ngăn aggregate PASS.</p>
<table><tr><th>Control</th><th>Owner</th><th>Aggregate</th><th>Records</th></tr>{coverage}</table>
<h2>Kết quả chi tiết</h2><label>Lọc trạng thái <select id="filter"><option value="">Tất cả</option>{''.join(f'<option>{s}</option>' for s in STATUSES)}</select></label>{detail}
<script>document.getElementById('filter').addEventListener('change',function(){{document.querySelectorAll('article').forEach(a=>a.hidden=this.value!==''&&a.dataset.status!==this.value)}})</script></html>'''
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document)
