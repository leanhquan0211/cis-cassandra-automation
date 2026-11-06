"""
cis_lab.cli
Owner: TV1 (Bùi Cao Minh Quân)
Role: CLI runner trung tâm điều phối 5 chế độ: preflight, audit, plan, apply, report.
"""

import argparse
import sys
import json
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser(description="CIS Apache Cassandra 4.0 Assessment & Hardening Framework")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. preflight
    p_preflight = subparsers.add_parser("preflight", help="Kiểm tra tiền điều kiện kết nối và môi trường")
    p_preflight.add_argument("--inventory", default="inventories/dev.yml", help="Đường dẫn inventory")

    # 2. audit
    p_audit = subparsers.add_parser("audit", help="Chạy đánh giá bảo mật 20 tiêu chí CIS")
    p_audit.add_argument("--inventory", default="inventories/dev.yml", help="Đường dẫn inventory")
    p_audit.add_argument("--policy", default="policies/lab.yml", help="Đường dẫn file chính sách")
    p_audit.add_argument("--out", default="artifacts/latest", help="Thư mục xuất kết quả")

    # 3. plan
    p_plan = subparsers.add_parser("plan", help="Lập kế hoạch khắc phục từ file kết quả audit")
    p_plan.add_argument("--input", required=True, help="File results.json")
    p_plan.add_argument("--out", required=True, help="Đường dẫn xuất plan.json")

    # 4. apply
    p_apply = subparsers.add_parser("apply", help="Thực thi áp dụng khắc phục theo plan đã được duyệt")
    p_apply.add_argument("--plan", required=True, help="Đường dẫn plan.json")
    p_apply.add_argument("--approval", required=True, help="Đường dẫn file approval đã ký")

    # 5. report
    p_report = subparsers.add_parser("report", help="Xuất báo cáo HTML và JSON từ kết quả")
    p_report.add_argument("--input", required=True, help="File results.json")
    p_report.add_argument("--out", default="artifacts/latest/report.html", help="Đường dẫn file HTML")

    args = parser.parse_args()

    print(f"[CIS-LAB] Đang thực thi lệnh: {args.command}...")
    # NOTE: TV1 hoàn thiện runner tích hợp các module checks/platform, auth, access, observability_tls
    return 0

if __name__ == "__main__":
    sys.exit(main())
