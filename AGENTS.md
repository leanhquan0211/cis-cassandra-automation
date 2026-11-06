# AGENTS.md — Quy tắc bắt buộc dành cho AI Agent hỗ trợ các thành viên

> **MỤC ĐÍCH TÀI LIỆU:**
> Tài liệu này là bản quy ước kỹ thuật tối cao dành cho các AI Agent (ChatGPT, Claude, Gemini, Copilot, Cursor, Windsurf, v.v.) đang hỗ trợ bất kỳ thành viên nào trong nhóm 4 người (`TV1`, `TV2`, `TV3`, `TV4`).
> Mọi Agent khi được nạp vào codebase này **BẮT BUỘC PHẢI ĐỌC VÀ TUÂN THỦ TUYỆT ĐỐI** các quy tắc dưới đây nhằm đảm bảo các thành viên làm việc độc lập 100% không bao giờ xảy ra xung đột mã nguồn (Git conflict) hay đè cấu hình của nhau.

---

## 1. Ranh giới sở hữu File và Thư mục (Zero Cross-Boundary Rule)

Mỗi Agent chỉ được phép tạo, chỉnh sửa và xóa các file nằm trong **vùng sở hữu** của thành viên mà Agent đó đang hỗ trợ. **Tuyệt đối cấm Agent chỉnh sửa file thuộc quyền sở hữu của thành viên khác.**

| Thành viên | Phụ trách chính | Thư mục & File Agent ĐƯỢC PHÉP chỉnh sửa | File CẤM Agent tự ý sửa |
| :--- | :--- | :--- | :--- |
| **TV1** *(Bùi Cao Minh Quân)* | Nền tảng Linux, Bootstrap, Runner chung, Config Renderer | • `bootstrap/`<br>• `ansible/roles/platform/`<br>• `checks/platform/`<br>• `config/render.py`<br>• `cis_lab/cli.py`<br>• `ansible/site.yml` | `checks/auth/`<br>`checks/access/`<br>`checks/observability_tls/`<br>`cis_lab/connection.py`<br>`cis_lab/report.py` |
| **TV2** *(Đoàn Thanh Đệ)* | Xác thực (Auth), Phân quyền cơ bản, Helper CQL | • `ansible/roles/auth/`<br>• `checks/auth/`<br>• `cis_lab/connection.py` | `checks/platform/`<br>`checks/access/`<br>`checks/observability_tls/`<br>`config/render.py` |
| **TV3** *(Đoàn Văn Tài)* | Chính sách (Policy), Rà soát quyền, Report & Schema | • `policies/`<br>• `schemas/`<br>• `checks/access/`<br>• `cis_lab/report.py` | `checks/platform/`<br>`checks/auth/`<br>`checks/observability_tls/`<br>`config/render.py` |
| **TV4** *(Lê Anh Quân)* | Log, Audit Log, Mã hóa đường truyền TLS | • `ansible/roles/observability_tls/`<br>• `checks/observability_tls/` | `checks/platform/`<br>`checks/auth/`<br>`checks/access/`<br>`cis_lab/connection.py`<br>`cis_lab/report.py` |

---

## 2. Quy tắc quản lý Cấu hình `cassandra.yaml` (Namespace Separation)

**Nghiêm cấm dùng lệnh `grep`, `sed`, `echo >>` để chèn bừa bãi vào file `cassandra.yaml`.**

Khi một Agent viết Ansible role hoặc script khắc phục (Remediation/Apply), Agent chỉ được xuất ra một Dictionary các khóa thuộc namespace của mình:

* **TV1 sở hữu:** `cluster_name`, `seed_provider`, `data_file_directories`, `commitlog_directory`, `saved_caches_directory`.
* **TV2 sở hữu:** `authenticator`, `authorizer`, `role_manager`.
* **TV3 sở hữu:** `listen_address` hoặc `listen_interface`, `network_authorizer`, `rpc_address`.
* **TV4 sở hữu:** `audit_logging_options`, `server_encryption_options`, `client_encryption_options`.

> **Cơ chế ghép:** File `config/render.py` (do TV1 quản lý) sẽ làm nhiệm vụ nạp các dictionary trên và merge an toàn vào file `cassandra.yaml` gốc. Nếu Agent của TV4 ghi đè vào `authenticator` hoặc Agent của TV2 sửa `audit_logging_options`, bộ merge sẽ từ chối và báo lỗi vi phạm phân quyền.

---

## 3. Quy tắc tuân thủ Định dạng Kết quả (`schemas/results.json`)

Mọi hàm kiểm tra (Checker) do Agent viết trong thư mục `checks/` **bắt buộc** phải trả về đối tượng `dict` tuân thủ đúng JSON Schema tại `schemas/results.json`:

```python
{
    "schema_version": "1.0",
    "run_id": "run-id-tu-cli",
    "timestamp_utc": "2026-11-06T12:00:00Z",
    "control_id": "4.1",                 # Định dạng chuẩn: ^[1-5]\.[1-8]$
    "owner": "TV4",                      # TV1 | TV2 | TV3 | TV4
    "cis_status": "A",                   # A (Automated) | M (Manual)
    "scope": "node",                     # node | cluster
    "target": "cass-dev1",               # Hostname hoặc IP của target
    "status": "PASS",                    # PASS | FAIL | NEEDS_REVIEW | ERROR | NOT_IMPLEMENTED | NOT_APPLICABLE
    "actual": "Log level is INFO",       # Giá trị thực tế đã che mật khẩu/bí mật
    "expected": "Log level is not OFF",  # Giá trị mong đợi theo policy
    "evidence": "stdout snippet...",     # Log hoặc bằng chứng kiểm chứng
    "policy_ref": "policies/lab.yml",    # Đường dẫn file policy
    "reason": "Giải thích ngắn gọn lý do kết luận",
    "duration_ms": 12.5                  # Thời gian thực thi (ms)
}
```

### Quy tắc gán `status`:
* **`PASS`**: Thỏa mãn 100% điều kiện kỹ thuật và chính sách.
* **`FAIL`**: Không đạt chuẩn an toàn theo benchmark/policy.
* **`NEEDS_REVIEW`**: Thu thập được dữ liệu nhưng thiếu chính sách đối chiếu (ví dụ: phát hiện role người dùng nhưng policy chưa có danh sách phê duyệt). **Tuyệt đối không tự biến NEEDS_REVIEW thành PASS.**
* **`ERROR`**: Không kết nối được tới node, timeout, sai SSH key, lệnh bị crash. **Tuyệt đối không chuyển lỗi kết nối thành PASS hay FAIL.**
* **`NOT_IMPLEMENTED`**: Tiêu chí chưa viết code collector/đánh giá (dùng cho các tiêu chí giai đoạn sau).

---

## 4. Quy tắc Môi trường: Hỗ trợ Máy ảo Cloud thay vì VMware

Mặc dù kế hoạch ban đầu đề cập VMware Workstation Pro, **dự án chính thức chấp thuận việc triển khai toàn bộ máy ảo trên Cloud (AWS, GCP, Azure, DigitalOcean, VPS)** do rào cản phần cứng laptop cá nhân không đủ RAM.

Mọi Agent cần tuân thủ cấu hình mạng Cloud như sau:
1. **Dải mạng khuyến nghị (Private Subnet / VPC):** Cấu hình VPC có dải Private IP `192.168.56.0/24`:
   * `ctrl-dev` (Controller): `192.168.56.10`
   * `cass-dev1` (Cassandra Node 1): `192.168.56.11`
   * `cass-dev2` (Cassandra Node 2): `192.168.56.12`
   * `cass-int3` (Cassandra Node 3): `192.168.56.13`
2. **Nếu Cloud cấp IP ngẫu nhiên:** Agent chỉ cần cập nhật IP vào file `inventories/dev.yml` và biến `allowed_node_networks` trong `policies/lab.yml`. Không hardcode IP trực tiếp trong code Python.
3. **Tường lửa (Cloud Security Group):**
   * Chỉ mở cổng `22` (SSH), `7000` (Inter-node cluster), `9042` (CQL transport) **trong nội bộ dải VPC**.
   * **CẤM** mở cổng `7000` và `9042` ra Internet công cộng (`0.0.0.0/0`).

---

## 5. Các điều CẤM TUYỆT ĐỐI (Strictly Prohibited)

1. **CẤM Hardcode mật khẩu hoặc Commit Private Key:**
   * Không bao giờ đưa file `.key`, `.pem`, `.p12`, `.jks`, keystore password vào Git.
   * Mọi output evidence phải được che mật khẩu (masking, ví dụ `password=***`).
2. **CẤM Tắt xác thực để "vượt test" (Bypass Verification):**
   * Trong module TLS (5.1, 5.2): Cấm bật chế độ bỏ qua xác minh SSL (`skip_verification = true`, `insecure = true`).
3. **CẤM Thay đổi phiên bản phần mềm cốt lõi:**
   * Node Cassandra bắt buộc dùng **Cassandra 4.0.19** và **Java 8 (Temurin 8u472)**. Không tự ý nâng cấp lên Cassandra 5.x hoặc Java 11/17 vì sẽ gây sai lệch baseline CIS v1.3.0.
4. **CẤM Tự động Apply mà không có Plan & Approval:**
   * Các thay đổi nhạy cảm (đổi pass, thu hồi superuser, bật TLS) bắt buộc phải qua chu trình: `audit` $\rightarrow$ sinh `plan.json` $\rightarrow$ xác nhận `approval.json` $\rightarrow$ `apply`.
5. **CẤM Commit trực tiếp lên nhánh `main`:**
   * Agent luôn làm việc trên nhánh tính năng của thành viên:
     * TV1: `feature/platform`
     * TV2: `feature/auth`
     * TV3: `feature/access-policy`
     * TV4: `feature/observability-tls`
