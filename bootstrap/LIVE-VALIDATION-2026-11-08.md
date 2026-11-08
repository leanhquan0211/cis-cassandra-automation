# TV1 — kiểm chứng trên cass-dev1, 08/11/2026

Đây là biên bản VM thật, tách khỏi các báo cáo fixture trước đó. Chưa kết luận
toàn bộ lab hoặc toàn bộ đồ án đạt.

## Đã kiểm chứng nền tảng VM

- VM VMware `cass-dev1`, Ubuntu Server 22.04.5 LTS, hostname `cass-dev1`.
- 3.072 MiB RAM cấu hình, 2 vCPU, đĩa ảo sparse 40 GiB.
- NAT `172.16.200.128/24`, default gateway/DNS `172.16.200.2`.
- Host-only `192.168.56.11/24`, không có default route trên card này.
- Laptop SSH được vào host-only bằng host key đã đối chiếu với console VM.
- HTTPS ra Internet thành công, OpenSSH và open-vm-tools hoạt động,
  Python 3 đã cài; cloud-init hoàn thành không có lỗi hoặc recoverable_errors.

Bằng chứng gốc nằm ngoài Git:
`~/VMs/cass-dev1/live-verification-20261108T100236Z.json` (13 kiểm tra đạt).
Không đưa private key, password hoặc cloud-init seed vào repository.

Host dùng VMware 26.0.1 build 25688693 trên kernel 7.0.0-42-generic.
Module gốc vmmon/vmnet đã build và chạy VM thực tế, nhưng kernel này vượt mốc
7.0.0-30 được liệt kê cho Ubuntu 26.04 trong
[ma trận Broadcom](https://knowledge.broadcom.com/external/article/315653).
Không coi việc chạy được là chứng nhận tương thích chính thức.

## Triển khai và kiểm chứng dịch vụ: đạt phạm vi một node TV1

Chạy `bootstrap/live-platform.yml` với inventory cục bộ ngoài Git, giới hạn
`cass-dev1`. Không sửa inventory, policy hoặc namespace của thành viên khác.

- Temurin 1.8.0_472-b08 và Cassandra 4.0.19 cài từ tarball chính thức, SHA256
  của cả hai tarball khớp giá trị đã khóa trong defaults.
- Cassandra chạy bằng UID 997/GID 998 (`cassandra`), không phải root.
- `nodetool version` trả `ReleaseVersion: 4.0.19`; `nodetool status` có node
  `UN 127.0.0.1` (một node biệt lập).
- CQL chỉ đọc `SELECT release_version, cluster_name FROM system.local;`
  trả `4.0.19 | CISLab`.
- Các cổng 7000, 7199, 9042 chỉ lắng nghe trên loopback trong VM; không có
  NAT port-forward ra Internet.
- Chrony đồng bộ thật; offset ghi nhận lúc audit là 2,991125 ms, nhỏ hơn
  giới hạn 100 ms trong policy.
- Bootstrap chạy lại không đổi PID JVM và checksum `cassandra.yaml`.
  Không có task thay đổi trong lượt platform thứ hai. Lượt sửa cuối cùng:
  `ok=61 changed=2 unreachable=0 failed=0 skipped=10`, exit 0; hai thay đổi
  ở lượt đầu là bổ sung stock config và restart có điều kiện để nạp startup files.
- Lượt đầu tải Temurin bị timeout 10 giây. Đã tăng timeout 120 giây và thêm
  thử lại, giữ nguyên URL chính thức, checksum và xác minh TLS.
- VMware từng nhận SIGHUP do Terminal khởi chạy đóng. Đã tách session khi bật
  VM; không thay kernel, không giảm bảo vệ hệ thống và không force-power-off.
- Lỗi copy thư mục `remote_src + force=false` từng bỏ qua stock startup files,
  khiến JMX không chạy dù CQL đã lên. Đã sửa copy từng file thiếu, giữ nguyên
  file đã tồn tại và YAML thuộc các namespace; thêm chờ JMX trước nodetool.

Log triển khai nằm tại `~/VMs/cass-dev1/platform/logs/`; mỗi lượt dùng file riêng.
Log thất bại được giữ để phân biệt lỗi mạng, sudo và lỗi dịch vụ.

Bằng chứng dịch vụ: `platform/runs/service-verification-20261108T110229Z.json`
trong thư mục VM, 10/10 kiểm tra đạt. Log playbook thành công:
`platform/logs/deploy-retry-20261108T110038Z.log`.

## Preflight và audit SSH thật

Chạy bằng policy nhóm `policies/lab.yml`, không dùng `--fixture` hoặc policy test.
Run ID `run-cad4c4c14c1c45a39e844a801d5106a9`, source_mode `ssh`.

| Control | Kết quả | Bằng chứng chính |
| --- | --- | --- |
| 1.1 | PASS (M) | User/group Cassandra riêng, UID 997, GID 998 |
| 1.2 | PASS | JVM thực chạy là Temurin 1.8.0_472 |
| 1.3 | NEEDS_REVIEW | Python 3.10.12; thiếu minimum_python_version trong policy |
| 1.4 | PASS | Nodetool kết nối JVM thật, release 4.0.19 |
| 1.5 | PASS | CassandraDaemon active, PID 5040, effective UID 997 |
| 1.6 | PASS (M) | Chrony synchronized, offset 2,991125 ms |
| 3.4 | PASS | Unit User/Group và UID/GID tiến trình khớp account riêng |

Audit trả exit 3 với **6 PASS, 1 NEEDS_REVIEW, 0 FAIL, 0 ERROR**.
Preflight có thêm supported_os PASS, vẫn `ready=false`, exit 3 vì policy thiếu.
Không biến thiếu policy thành PASS. Nhãn M giữ nguyên: kết quả kỹ thuật không thay
thế rà soát thủ công toàn bộ benchmark.

Thư mục gốc: `~/VMs/cass-dev1/platform/runs/live-ujgMLiRw/`.
`audit/results.json` tuân schema và hash khớp `audit/run.json`.
Plan từ run thật có 0 action, một kết quả blocked; template approval vẫn trống,
chưa được duyệt. Không thực thi remediation.

Bản chụp bằng chứng không chứa bí mật nằm tại
[evidence/live-2026-11-08](evidence/live-2026-11-08/).

## Code và fixture

79 unit tests đạt sau lần sửa timeout tải file; syntax-check playbook và
`git diff --check` đạt. Fixture đúng/sai/lỗi đọc và hỗn hợp giữ đúng trạng thái PASS/FAIL/ERROR.
Kết quả fixture không dùng làm bằng chứng dịch vụ thật.

Runner có `--ssh-config` cho alias và known_hosts được pin; `--ask-become-pass`
chỉ cho live SSH cùng `--become`, nhập không echo và không lưu password. Password
được truyền qua stdin cho sudo, không nằm trong argv hoặc mã Python thực thi.

## Phần cần phối hợp hoặc chưa triển khai

- Policy nhóm chưa có `platform.minimum_python_version`: control 1.3 phải giữ
  NEEDS_REVIEW đến khi TV3 duyệt policy. Không dùng fixture-policy để vượt audit thật.
- Nhãn M của 1.1 và 1.6 vẫn cần đối chiếu thủ công theo benchmark.
- Mới có một node; chưa kiểm chứng cluster nhiều node, liên lạc giữa node hoặc TLS.
- Chưa kiểm chứng tự khởi động Cassandra sau reboot VM. Chưa kiểm chứng CQL/TLS
  từ controller; truy vấn CQL phía trên chạy tại loopback trong VM.
- Module auth/access/observability_tls và HTML report thuộc TV2–TV4, không viết thay.
- Apply thật chưa có backend và chưa xác thực danh tính người duyệt; runner từ chối
  thực thi. Dry-run/approval fixture không cấp quyền thay đổi dịch vụ thật.

## Kết nối và bật/tắt

```bash
ssh -F ~/VMs/cass-dev1/ssh-config cass-dev1
python3 ~/VMs/cass-dev1/control.py status
python3 ~/VMs/cass-dev1/control.py start
python3 ~/VMs/cass-dev1/control.py stop
```

`start` giữ điều kiện ít nhất 3.840 MiB RAM khả dụng. `stop` chỉ shutdown mềm,
không cưỡng bức tắt. File VM: `~/VMs/cass-dev1/cass-dev1.vmx`.
