"""PDF acceptance checks: Unicode, truthful summaries, provenance and CLI outputs."""
import json
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfReader
import pytest

from checks.access.common import result
from checks.access.pdf_report import generate_comparison_pdf
from cis_lab.report import generate_pdf_report


def row(control="3.8", target="CISLab", status="PASS", **values):
    data = dict(run_id="fixture-one", policy_ref="fixture-policy", evidence="FIXTURE synthetic data")
    data.update(values)
    actual = {"effective_superusers": ["lab_dba"], "unauthorized": [], "missing": []}
    return result(control, target, status, actual, {}, "FIXTURE observation", **data)


def text(path):
    return "\n".join(p.extract_text() for p in PdfReader(path).pages)


def test_pdf_preserves_vietnamese_without_personal_or_time_labels(tmp_path):
    record = row()
    record["timestamp_utc"] = "2026-11-07T15:20:00Z"
    path = tmp_path / "report.pdf"
    generate_pdf_report([record], path, source_path="results.json")
    content = text(path)
    assert "KẾT QUẢ KIỂM TRA CASSANDRA" in content
    assert "07/11/2026" not in content and "Xuất PDF:" not in content
    assert record['run_id'] not in content and 'Người thực hiện' not in content
    assert "DỮ LIỆU GIẢ LẬP" in content and "lab_dba" in content
    assert not PdfReader(path).metadata.author
    assert "effective_superusers" not in content  # Human explanation, not a JSON dump.


def test_pdf_reports_inherited_excess_permission_without_secret_or_markup(tmp_path):
    record = row(control="3.3", status="FAIL")
    record["actual"] = {"violations": [{"kind": "excess_permission", "role": "app_reader",
        "granted_to": "reader_role", "permission": "MODIFY", "resource": "data/table/cis_demo/items"}]}
    record["target"] = "<b>CISLab</b> password=PRIVATE_SENTINEL"
    path = tmp_path / "report.pdf"
    generate_pdf_report([record], path)
    content = text(path)
    assert "MODIFY qua role reader_role" in content and "Không đạt" in content
    assert "PRIVATE_SENTINEL" not in content
    assert "<b>CISLab</b>" in content  # External markup is literal text, not formatting.


def test_pdf_retains_partial_node_error_and_shows_only_provided_controls(tmp_path):
    records = [row("3.5", "node-one"), row("3.5", "node-two", "ERROR")]
    path = tmp_path / "report.pdf"
    generate_pdf_report(records, path)
    content = text(path)
    assert "Lỗi thu thập" in content
    assert "0 mã có kết luận" in content
    assert "1.1" not in content  # Missing controls are not padded into twenty rows.


def test_empty_and_mixed_run_pdf_do_not_claim_compliance(tmp_path):
    path = tmp_path / "empty.pdf"
    generate_pdf_report([], path)
    assert "Chưa có dữ liệu kiểm tra" in text(path)
    with pytest.raises(ValueError):
        generate_pdf_report([row(), row(target="other", run_id="fixture-two")], tmp_path / "mixed.pdf")


def test_healthy_three_node_midterm_fits_one_page(tmp_path):
    records = [row("3.3"), row(), row("3.6", status="NOT_IMPLEMENTED"), row("3.7", status="NOT_IMPLEMENTED")]
    records[0]["actual"] = {"observed_role_count": 6, "violations": []}
    for i in range(1, 4):
        record = row("3.5", "cass-dev" + str(i))
        record["actual"] = {"config": {"listen_address": "192.168.56." + str(10+i)}}
        records.append(record)
    path = tmp_path / "healthy.pdf"
    generate_pdf_report(records, path)
    assert len(PdfReader(path).pages) == 1
    assert all("cass-dev" + str(i) in text(path) for i in range(1, 4))


def test_pdf_discloses_omitted_details_and_wraps_long_resources(tmp_path):
    record = row("3.3", status="FAIL")
    record["actual"] = {"violations": [{"kind": "excess_permission", "role": "app_reader",
        "granted_to": "reader_role", "permission": "MODIFY", "resource": "data/table/" + "long_resource_" * 18}
        for _ in range(20)]}
    path = tmp_path / "long.pdf"
    generate_pdf_report([record], path)
    assert "Còn 14 phát hiện" in text(path)


def test_comparison_keeps_runs_separate_and_warns_about_fixture(tmp_path):
    path = tmp_path / "comparison.pdf"
    generate_comparison_pdf({"clean": [row()], "restored": [row(run_id="fixture-two")]}, path)
    content = text(path)
    assert len(PdfReader(path).pages) >= 1
    assert "Có dữ liệu giả lập" in content
    assert "Đúng chính sách: 1 đạt, 0 không đạt" in content
    assert "Sau khi khôi phục: 1 đạt, 0 không đạt" in content


def test_cli_exports_pdf_and_rejects_mismatched_matrix(tmp_path, monkeypatch):
    from checks.access.__main__ import main
    source = tmp_path / "results.json"
    source.write_text(json.dumps([row()]))
    output = tmp_path / "report.pdf"
    monkeypatch.setattr("sys.argv", ["checks.access", "report", "--input", str(source), "--out", str(output)])
    assert main() == 0 and output.read_bytes().startswith(b"%PDF-")
    case = tmp_path / "clean"
    case.mkdir()
    (case / "results.json").write_text(source.read_text())
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps({"matrix": [{"scenario": "clean", "PASS": 99}]}))
    monkeypatch.setattr("sys.argv", ["checks.access", "report", "--matrix", str(matrix), "--out", str(tmp_path / "invalid.pdf")])
    assert main() == 1 and not (tmp_path / "invalid.pdf").exists()


def test_audit_creates_readable_pdf_and_keeps_group_html(tmp_path, monkeypatch):
    from checks.access.__main__ import main
    source = tmp_path / "input.yml"
    source.write_text("{}")
    output = tmp_path / "audit"
    monkeypatch.setattr("checks.access.__main__.inventory_nodes", lambda value: {"node": {"ansible_host": "192.0.2.1"}})
    monkeypatch.setattr("checks.access.__main__.SSHCollector", lambda *a, **k: SimpleNamespace(cache={}))
    monkeypatch.setattr("checks.access.__main__.run_all_checks", lambda *a, **k: [row()])
    monkeypatch.setattr("sys.argv", ["checks.access", "audit", "--inventory", str(source), "--policy", str(source),
        "--ssh-config", "fixture-ssh", "--out", str(output)])
    assert main() == 0
    assert (output / "report.pdf").read_bytes().startswith(b"%PDF-")
    assert (output / "report.html").exists() and (output / "results.json").exists()
