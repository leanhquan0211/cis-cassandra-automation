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
from checks.access.report_text import CONTROL_NAMES, STATUS_NAMES, describe_result


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
    coverage = "".join(
        f'<tr><td>{text(cid)}</td><td>{text(CONTROL_NAMES[cid])}</td>'
        f'<td>{text(STATUS_NAMES[item["aggregate_status"]])}</td></tr>'
        for cid,item in summary["controls"].items())
    details = []
    for row in rows:
        if row["status"] in ("NOT_IMPLEMENTED", "NOT_APPLICABLE"):
            continue
        lines = describe_result(row)
        paragraphs = "".join(f'<p>{text(line)}</p>' for line in lines[:6])
        if len(lines) > 6:
            paragraphs += f'<p>Còn {len(lines)-6} phát hiện. Xem results.json để đọc đầy đủ.</p>'
        details.append(
            f'<article data-status="{text(row["status"])}"><h3>{text(row["control_id"])}. '
            f'{text(CONTROL_NAMES[row["control_id"]])} ({text(row["target"])})</h3>{paragraphs}</article>')
    detail = "".join(details)
    fixture = any("FIXTURE" in r["evidence"].upper() or "SIMULATED" in r["evidence"].upper() for r in rows)
    totals = ", ".join(f'{summary["status_counts"][status]} {STATUS_NAMES[status].lower()}'
                       for status in STATUSES if summary["status_counts"][status])
    if not rows:
        totals = "Chưa có dữ liệu kiểm tra."
    missing = len(summary["missing_controls"])
    missing_note = f'<p>Còn {missing} mục chưa có kết quả. Các mục này chưa được kết luận là đạt.</p>' if missing else ""
    fixture_note = '<p>DỮ LIỆU FIXTURE: dùng để thử chương trình, không phải kết quả từ máy thật.</p>' if fixture else ""
    document = f'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kết quả kiểm tra Cassandra</title><style>
body{{font:17px/1.5 "Times New Roman",serif;max-width:850px;margin:32px auto;padding:0 20px;color:#111;background:white}}
h1{{font-size:25px;text-align:center}}h2{{font-size:21px;margin-top:24px}}h3{{font-size:18px;margin:16px 0 6px}}
p{{margin:7px 0}}table{{border-collapse:collapse;width:100%;margin:12px 0}}td,th{{padding:6px 9px;border:1px solid #999;text-align:left}}th{{background:#f2f2f2}}
article{{break-inside:avoid}}select{{font:inherit}}.tools{{margin:16px 0}}
@media print{{@page{{size:A4;margin:18mm}}body{{margin:0;padding:0;font-size:11pt;max-width:none}}h1{{font-size:17pt}}h2{{font-size:14pt}}h3{{font-size:12pt}}.tools{{display:none}}th{{background:white}}thead{{display:table-header-group}}article[hidden]{{display:block}}}}
</style><h1>KẾT QUẢ KIỂM TRA CASSANDRA</h1>
{fixture_note}<p>Chương trình đọc cấu hình và quyền truy cập, rồi so với chính sách được duyệt.</p>
<p><strong>Kết quả: {text(totals)}</strong></p>
<p>Số trên đếm theo bản ghi. Một mục có thể được kiểm tra trên nhiều máy.</p>{missing_note}
<table><thead><tr><th>Mã</th><th>Nội dung kiểm tra</th><th>Kết quả</th></tr></thead><tbody>{coverage}</tbody></table>
<h2>Giải thích kết quả</h2><div class="tools"><label>Lọc kết quả: <select id="filter"><option value="">Tất cả</option>{''.join(f'<option value="{s}">{text(STATUS_NAMES[s])}</option>' for s in STATUSES)}</select></label></div>{detail}
<p>Dữ liệu và bằng chứng nằm trong results.json và thư mục evidence/. Báo cáo trình bày kết quả đã lưu.</p>
<script>document.getElementById('filter').addEventListener('change',function(){{document.querySelectorAll('article').forEach(a=>a.hidden=this.value!==''&&a.dataset.status!==this.value)}})</script></html>'''
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document)


def generate_pdf_report(results, output_path, *, source_path=None):
    """Printable Vietnamese report; imported lazily for existing HTML callers."""
    from checks.access.pdf_report import generate_pdf_report as render_pdf
    return render_pdf(results, output_path, source_path=source_path)
