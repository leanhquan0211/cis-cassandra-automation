# Bằng chứng phục hồi và khởi động lại VM thật

Không dùng fixture. Không chứa private key, password hoặc cloud-init seed.

- `cold-start-service.json`: 15 kiểm tra thật sau bật VM bằng nogui.
- `results.json`, `run.json`: audit SSH có sudo sau cold start, trước reboot mềm;
  6 PASS, 1 NEEDS_REVIEW, exit 3. Hash results khớp run metadata.
- `after-soft-reboot-service.json`: 15 kiểm tra thật sau `vmrun reset ... soft`.
- `summary.json`: boot ID trước/sau, trạng thái service, tài nguyên và giới hạn.

Không chạy lệnh start Cassandra trong quy trình này: systemd tự khởi động service.
Boot ID đổi xác nhận hệ điều hành đã khởi động lại; MainPID mới và NRestarts=0.
Kiểm tra CQL chỉ đọc chạy trên loopback bên trong guest, không phải CQL/TLS từ laptop.
Đây là kiểm chứng phục hồi trong thời gian quan sát, không chứng nhận tương thích
kernel VMware hoặc ổn định dài hạn. Lab nhiều node và các module khác chưa nghiệm thu.
