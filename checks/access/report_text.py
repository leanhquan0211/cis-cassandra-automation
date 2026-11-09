"""Short Vietnamese labels and explanations shared by HTML and PDF reports."""

CONTROL_NAMES = {
    "1.1": "User và group Linux riêng", "1.2": "Phiên bản Java",
    "1.3": "Phiên bản Python", "1.4": "Phiên bản Cassandra",
    "1.5": "Dịch vụ không chạy root", "1.6": "Đồng bộ đồng hồ",
    "2.1": "Bật xác thực", "2.2": "Bật phân quyền",
    "3.1": "Tách quyền quản trị mặc định", "3.2": "Mật khẩu mặc định",
    "3.3": "Role và quyền theo chính sách", "3.4": "Tài khoản dịch vụ ít quyền",
    "3.5": "Địa chỉ mạng được phép", "3.6": "Quyền theo datacenter",
    "3.7": "Rà soát quyền qua role", "3.8": "Rà soát superuser",
    "4.1": "Log hoạt động", "4.2": "Audit log",
    "5.1": "TLS giữa các node", "5.2": "TLS từ client",
}
STATUS_NAMES = {
    "PASS": "Đạt", "FAIL": "Không đạt", "NEEDS_REVIEW": "Cần rà soát",
    "ERROR": "Lỗi thu thập", "NOT_IMPLEMENTED": "Chưa triển khai",
    "NOT_APPLICABLE": "Không áp dụng", "NO_RESULT": "Chưa có kết quả",
}
CASE_NAMES = {
    "clean": "Đúng chính sách", "drift": "Có sai lệch thử nghiệm",
    "restored": "Sau khi khôi phục", "missing-policy": "Thiếu phê duyệt policy",
    "expired-policy": "Policy hết hạn", "ssh-error": "Lỗi kết nối SSH",
}

def describe_result(row):
    """Explain structured findings, without dumping sockets, credentials or logs."""
    actual = row.get("actual") if isinstance(row.get("actual"), dict) else {}
    status, control = row["status"], row["control_id"]
    if status == "ERROR":
        return ["Không lấy được đủ dữ liệu từ " + row["target"] + ". Chưa thể kết luận đạt hay không đạt. " + row["reason"][:180]]
    if status == "NEEDS_REVIEW":
        reason = row["reason"]
        if "expired" in reason.lower():
            return ["Policy đã hết hạn hoặc thời hạn không hợp lệ; cần rà soát trước khi kết luận."]
        if "approver" in reason.lower():
            return ["Policy chưa ghi nhận người phê duyệt; dữ liệu đã lấy được chưa đủ để kết luận đạt."]
        return ["Cần người phụ trách rà soát: " + reason[:240]]
    if status == "NOT_IMPLEMENTED":
        return ["Chưa có bộ đánh giá cho tiêu chí này."]
    if control == "3.3":
        output = []
        for item in actual.get("violations", []):
            kind, role = item.get("kind"), str(item.get("role", "?"))
            if kind == "excess_permission":
                parent = item.get("granted_to", role)
                via = " qua role " + str(parent) if parent != role else ""
                output.append(role + " có quyền thừa " + str(item.get("permission")) + via + " trên " + str(item.get("resource")) + ".")
            elif kind == "missing_permission":
                output.append(role + " thiếu quyền cần có " + str(item.get("permission")) + " trên " + str(item.get("resource")) + ".")
            elif kind == "unapproved_role":
                output.append("Role " + role + " nằm ngoài danh sách được duyệt.")
            elif kind == "missing_role":
                output.append("Không tìm thấy role " + role + " theo policy.")
            elif kind == "effective_superuser":
                output.append(role + " có superuser hiệu lực ngoài policy.")
            else:
                output.append("Thuộc tính hoặc quan hệ role của " + role + " khác policy; xem results.json.")
        if output:
            return output
        if status == "PASS":
            return ["Đã kiểm tra " + str(actual.get("observed_role_count", "?")) + " role, không thấy quyền khác với quy định."]
        return ["Bộ kiểm tra ghi nhận sai lệch về role/quyền; xem results.json để đối chiếu."]
    if control == "3.5":
        config = actual.get("config", {})
        if status == "PASS":
            return ["Liên node: " + str(config.get("listen_address", config.get("listen_interface", "xem evidence"))) +
                    "; ứng dụng: " + str(config.get("rpc_address", config.get("rpc_interface", "xem evidence"))) +
                    ". Địa chỉ và cổng đang dùng đúng với mạng được phép."]
        return ["Cấu hình hoặc socket mạng không phù hợp policy. " + row["reason"][:180]]
    if control == "3.8":
        output = ["Tài khoản có quyền quản trị cao nhất: " + ", ".join(map(str, actual.get("effective_superusers", []))) + "."]
        if actual.get("unauthorized"):
            output.append("Ngoài policy: " + ", ".join(map(str, actual["unauthorized"])) + ".")
        if actual.get("missing"):
            output.append("Thiếu superuser theo policy: " + ", ".join(map(str, actual["missing"])) + ".")
        return output
    return [row["reason"][:300]]
