# CIS Apache Cassandra 4.0 Security Automation Framework (`cis_lab`)

Hệ thống công cụ tự động hóa đánh giá, đối chiếu chính sách và khắc phục cấu hình an toàn thông tin cho **Apache Cassandra 4.0** dựa trên chuẩn **CIS Apache Cassandra 4.0 Benchmark v1.3.0**.

---

## 1. Phân công Trách nhiệm & Quyền sở hữu (Team & Ownership Matrix)

Dự án áp dụng mô hình **Phân quyền độc lập theo thư mục (Zero-Cross-Boundary)** để 4 thành viên và các AI Agent có thể làm việc song song 100% mà không gây xung đột Git hay đè file cấu hình:

| Thành viên                  |   Mã   | Vai trò chính                                                     | Thư mục sở hữu (Chỉ người này được sửa)                                                                |         Tiêu chí CIS phụ trách         |
| :---------------------------- | :-----: | :------------------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------- | :-----------------------------------------: |
| **Bùi Cao Minh Quân** | `TV1` | Nền tảng Linux, Bootstrap, Runner chung, Config Renderer          | • `bootstrap/`• `ansible/roles/platform/`• `checks/platform/`• `config/render.py`• `cis_lab/cli.py` | **1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.4** |
| **Đoàn Thanh Đệ**   | `TV2` | Xác thực (Authentication), Phân quyền cơ bản, Helper CQL      | • `ansible/roles/auth/`• `checks/auth/`• `cis_lab/connection.py`                                          |        **2.1, 2.2, 3.1, 3.2**        |
| **Đoàn Văn Tài**    | `TV3` | Chính sách bảo mật (Policy), Rà soát quyền, Report HTML/JSON | • `policies/`• `schemas/`• `checks/access/`• `cis_lab/report.py`                                       |      **3.3, 3.5, 3.6, 3.7, 3.8**      |
| **Lê Anh Quân**       | `TV4` | Ghi log hệ thống, Audit Log, Mã hóa đường truyền TLS        | • `ansible/roles/observability_tls/`• `checks/observability_tls/`                                            |        **4.1, 4.2, 5.1, 5.2**        |

> ⚠️ **Quy tắc vàng cho các thành viên và AI Agent:**
> Chỉ được commit/chỉnh sửa file trong thư mục mình sở hữu. Tuyệt đối không sửa code của thư mục thành viên khác. Mọi Agent hỗ trợ phải đọc kỹ [AGENTS.md](file:///n:/OneDrive/UIT/HK1/NT542/Doan/AGENTS.md).

---

## 2. Kiến trúc Môi trường & Hạ tầng Lab (Cloud hoặc VMware)

Dự án chính thức chấp thuận 2 phương án hạ tầng để giải phóng tài nguyên phần cứng cá nhân:

### Phương án A (Khuyến nghị): Máy ảo trên Cloud (AWS / GCP / Azure / VPS)

* **Lý do:** Tránh việc laptop cá nhân không đủ RAM để chạy đồng thời 4 máy ảo.
* **Cấu hình mạng VPC (Virtual Private Cloud):**
  * Tạo một Subnet Private với dải mạng: `192.168.56.0/24`.
  * Gán Static Private IP cho các máy ảo như sau:
    * `ctrl-dev` (Controller điều phối): `192.168.56.10` (Ubuntu 26.04 hoặc 24.04 / 22.04 LTS)
    * `cass-dev1` (Cassandra Node 1): `192.168.56.11` (Ubuntu 22.04 LTS, JDK 8 Temurin, Cassandra 4.0.19)
    * `cass-dev2` (Cassandra Node 2 - test TLS): `192.168.56.12`
    * `cass-int3` (Cassandra Node 3 - tích hợp): `192.168.56.13`
  * *(Lưu ý: Nếu Cloud cấp IP ngẫu nhiên, chỉ cần cập nhật IP vào `inventories/dev.yml` và biến `allowed_node_networks` trong `policies/lab.yml`).*
* **Tường lửa (Cloud Security Group):**
  * Mở cổng `22` (SSH) từ máy Controller tới các Node.
  * Mở cổng `7000` (Giao tiếp cụm Cassandra) và `9042` (CQL native transport) **chỉ trong nội bộ subnet VPC**.
  * CẤM mở cổng `7000` và `9042` ra Internet công cộng (`0.0.0.0/0`).

### Phương án B: VMware Workstation Pro (Nội bộ)

* Máy tính cần tối thiểu 16GB–24GB RAM.
* Card 1: NAT (tải package). Card 2: Custom Host-only VMnet1 (`192.168.56.0/24`, tắt DHCP).

---

## 3. Cấu trúc Thư mục Dự án

```text
cis-cassandra-automation/
├── ansible/                          # Playbook và Roles tự động hóa
│   ├── site.yml                      # Playbook tổng hợp chạy các role theo thứ tự (TV1)
│   └── roles/
│       ├── platform/                 # Cài đặt nền tảng, systemd, user cassandra, NTP (TV1)
│       ├── auth/                     # Cấu hình PasswordAuthenticator, đổi pass cassandra (TV2)
│       └── observability_tls/        # Cấu hình Logback, BinAuditLogger, OpenSSL & TLS (TV4)
├── bootstrap/                        # Script cài đặt Cassandra 4.0.19 tarball ban đầu (TV1)
├── checks/                           # Module Python thực hiện đánh giá (Collectors & Evaluators)
│   ├── platform/                     # 1.1 - 1.6, 3.4 (TV1)
│   ├── auth/                         # 2.1, 2.2, 3.1, 3.2 (TV2)
│   ├── access/                       # 3.3, 3.5, 3.6, 3.7, 3.8 (TV3)
│   └── observability_tls/            # 4.1, 4.2, 5.1, 5.2 (TV4)
├── cis_lab/                          # Core Package Python của hệ thống
│   ├── __init__.py
│   ├── cli.py                        # Điểm vào dòng lệnh (CLI runner) (TV1)
│   ├── connection.py                 # Helper kết nối CQL driver trên node (TV2)
│   └── report.py                     # Render báo cáo report.html và results.json (TV3)
├── config/
│   └── render.py                     # Bộ ghép cấu hình cassandra.yaml theo namespace an toàn (TV1)
├── policies/
│   └── lab.yml                       # File chính sách bảo mật chuẩn của nhóm (TV3)
├── schemas/
│   └── results.json                  # JSON Schema 1.0 chuẩn cho output đánh giá (TV3)
├── inventories/
│   └── dev.yml                       # Danh sách máy chủ và IP kết nối Ansible
├── approvals/                        # Chứa các file approval đã ký duyệt trước khi apply
├── artifacts/                        # Thư mục chứa kết quả run (results.json, report.html, plan.json)
├── AGENTS.md                         # Hướng dẫn và rào chắn kỹ thuật cho AI Agent
└── README.md                         # Tài liệu hướng dẫn sử dụng
```

---

## 4. Quy ước Hợp nhất Cấu hình `cassandra.yaml` (Namespace Rules)

Để tránh tình trạng ghi đè hoặc xung đột file cấu hình trung tâm `/etc/cassandra/cassandra.yaml`, các thành viên chỉ được định nghĩa các khóa cấu hình thuộc thẩm quyền:

* **TV1:** `cluster_name`, `seed_provider`, `data_file_directories`, `commitlog_directory`, `saved_caches_directory`.
* **TV2:** `authenticator`, `authorizer`, `role_manager`.
* **TV3:** `listen_address` hoặc `listen_interface`, `network_authorizer`, `rpc_address`.
* **TV4:** `audit_logging_options`, `server_encryption_options`, `client_encryption_options`, và file `/etc/cassandra/logback.xml`.

Bộ ghép `config/render.py` sẽ tự động hợp nhất các dictionary trên vào file YAML gốc và từ chối nếu có thành viên ghi đè vào khóa của người khác.

---

## 5. Hướng dẫn Vận hành Khung Lệnh (CLI Interface)

Công cụ `cis_lab` cung cấp 5 chế độ hoạt động chuẩn:

```bash
# 1. Preflight: Kiểm tra kết nối SSH, phiên bản OS, Java, Cassandra
python -m cis_lab preflight --inventory inventories/dev.yml

# 2. Audit: Đánh giá hiện trạng bảo mật đối chiếu với chính sách lab.yml
python -m cis_lab audit --inventory inventories/dev.yml --policy policies/lab.yml --out artifacts/run01

# 3. Plan: Lập kế hoạch khắc phục từ các mục FAIL của kết quả audit
python -m cis_lab plan --input artifacts/run01/results.json --out artifacts/run01/plan.json

# 4. Apply: Thực thi khắc phục (chỉ chạy khi có file approval hợp lệ)
python -m cis_lab apply --plan artifacts/run01/plan.json --approval approvals/run01.json

# 5. Report: Tạo báo cáo HTML trực quan và trích xuất độ bao phủ
python -m cis_lab report --input artifacts/run01/results.json --out artifacts/run01/report.html
```

---

## 6. Ma trận 20 Tiêu chí CIS Apache Cassandra 4.0 Benchmark

| STT |    Mã CIS    | Tên tiêu chí                                        | Nhãn CIS | Phụ trách |      Mốc ưu tiên      |
| :-: | :-----------: | :----------------------------------------------------- | :-------: | :---------: | :----------------------: |
|  1  | **1.1** | Ensure a separate user and group exist for Cassandra   |     M     |     TV1     |        Giữa kỳ        |
|  2  | **1.2** | Ensure the latest version of Java is installed         |     A     |     TV1     |        Cuối kỳ        |
|  3  | **1.3** | Ensure the latest version of Python is installed       |     A     |     TV1     |        Cuối kỳ        |
|  4  | **1.4** | Ensure latest version of Cassandra is installed        |     A     |     TV1     |        Giữa kỳ        |
|  5  | **1.5** | Ensure the Cassandra service is run as a non-root user |     A     |     TV1     |        Giữa kỳ        |
|  6  | **1.6** | Ensure clocks are synchronized on all nodes            |     M     |     TV1     |        Giữa kỳ        |
|  7  | **2.1** | Ensure that authentication is enabled for Cassandra    |     A     |     TV2     |        Giữa kỳ        |
|  8  | **2.2** | Ensure that authorization is enabled for Cassandra     |     A     |     TV2     |        Giữa kỳ        |
|  9  | **3.1** | Ensure the cassandra and superuser roles are separate  |     A     |     TV2     |        Cuối kỳ        |
| 10 | **3.2** | Ensure default password is changed for cassandra role  |     A     |     TV2     |        Giữa kỳ        |
| 11 | **3.3** | Ensure no unnecessary roles or excessive privileges    |     M     |     TV3     |        Giữa kỳ        |
| 12 | **3.4** | Ensure Cassandra runs as a dedicated service account   |     A     |     TV1     |        Giữa kỳ        |
| 13 | **3.5** | Ensure Cassandra listens only on authorized interfaces |     M     |     TV3     |        Giữa kỳ        |
| 14 | **3.6** | Ensure that Data Center Authorizations is activated    |     M     |     TV3     |        Cuối kỳ        |
| 15 | **3.7** | Review User-Defined Roles                              |     M     |     TV3     |        Cuối kỳ        |
| 16 | **3.8** | Review Superuser/Admin Roles                           |     M     |     TV3     |        Giữa kỳ        |
| 17 | **4.1** | Ensure that logging is enabled (Logback / nodetool)    |     A     |     TV4     |        Giữa kỳ        |
| 18 | **4.2** | Ensure that auditing is enabled (BinAuditLogger)       |     M     |     TV4     | **Demo Giữa kỳ** |
| 19 | **5.1** | Inter-node Encryption (internode_encryption: all)      |     A     |     TV4     |        Cuối kỳ        |
| 20 | **5.2** | Client Encryption (client_encryption: enabled=true)    |     A     |     TV4     |        Cuối kỳ        |

---

## 7. Quy trình Phối hợp Nhóm Không cần Họp Thường Xuyên

1. **Khởi tạo:** Clone repository về máy, tạo branch riêng của mình:
   * TV1: `git checkout -b feature/platform`
   * TV2: `git checkout -b feature/auth`
   * TV3: `git checkout -b feature/access-policy`
   * TV4: `git checkout -b feature/observability-tls`
2. **Phát triển:** Mỗi thành viên tự kết nối tới VM cá nhân (hoặc Cloud VM được phân công) để code và test checker của mình trong `checks/<module>/`.
3. **Tuân thủ Format:** Mọi checker bắt buộc trả về dict chuẩn theo [schemas/results.json](file:///n:/OneDrive/UIT/HK1/NT542/Doan/schemas/results.json).
4. **Tích hợp:** Khi chạy thử tốt trên máy cá nhân, tạo Pull Request vào nhánh `main`. Bộ runner chung `cli.py` sẽ tự động phát hiện và gọi checker của bạn.
