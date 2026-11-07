#!/usr/bin/env bash
# ==============================================================================
# Script sinh Certificate Authority (CA) & Node Keystore/Truststore cho Cassandra
# Owner: TV4 (Lê Anh Quân)
# Chuẩn: OpenSSL + Java keytool với đầy đủ Subject Alternative Name (SAN)
# ==============================================================================

set -euo pipefail

TLS_DIR="/etc/cassandra/tls"
PASS="cassandra_lab_secret"
DAYS_VALID=365

mkdir -p "${TLS_DIR}"
cd "${TLS_DIR}"

echo "=== [TV4] Bước 1: Khởi tạo Root CA nội bộ ==="
if [ ! -f "ca.key" ]; then
    openssl genrsa -out ca.key 4096
    openssl req -x509 -new -nodes -key ca.key -sha256 -days "${DAYS_VALID}" \
        -subj "/C=VN/ST=HCM/L=ThuDuc/O=UIT/OU=NT542/CN=CISLab-RootCA" \
        -out ca.crt
    echo "-> Đã tạo Root CA (ca.key, ca.crt)"
fi

create_node_cert() {
    local NODE_NAME="$1"
    local NODE_IP="$2"

    echo "=== [TV4] Bước 2: Sinh Keystore & Certificate cho node: ${NODE_NAME} (${NODE_IP}) ==="

    # 1. Tạo file cấu hình OpenSSL với SAN
    cat > "${NODE_NAME}_san.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = VN
ST = HCM
L = ThuDuc
O = UIT
OU = NT542
CN = ${NODE_NAME}

[v3_req]
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${NODE_NAME}
DNS.2 = localhost
IP.1 = ${NODE_IP}
IP.2 = 127.0.0.1
EOF

    # 2. Sinh private key và CSR
    openssl genrsa -out "${NODE_NAME}.key" 2048
    openssl req -new -key "${NODE_NAME}.key" -out "${NODE_NAME}.csr" -config "${NODE_NAME}_san.cnf"

    # 3. Ký cert bằng Root CA
    openssl x509 -req -in "${NODE_NAME}.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
        -out "${NODE_NAME}.crt" -days "${DAYS_VALID}" -sha256 -extfile "${NODE_NAME}_san.cnf" -extensions v3_req

    # 4. Đóng gói thành PKCS12
    openssl pkcs12 -export -in "${NODE_NAME}.crt" -inkey "${NODE_NAME}.key" \
        -certfile ca.crt -out "${NODE_NAME}.p12" -name "${NODE_NAME}" -password "pass:${PASS}"

    # 5. Chuyển đổi PKCS12 sang Java Keystore (.jks hoặc giữ .p12)
    keytool -importkeystore -deststorepass "${PASS}" -destkeypass "${PASS}" \
        -destkeystore "${NODE_NAME}.keystore" -srckeystore "${NODE_NAME}.p12" \
        -srcstoretype PKCS12 -srcstorepass "${PASS}" -noprompt

    # 6. Tạo Truststore chứa Root CA
    keytool -import -trustcacerts -alias RootCA -file ca.crt \
        -keystore "${NODE_NAME}.truststore" -storepass "${PASS}" -noprompt

    # Phân quyền cho user cassandra
    chmod 640 "${NODE_NAME}".* ca.crt
    if id -u cassandra >/dev/null 2>&1; then
        chown cassandra:cassandra "${NODE_NAME}".* ca.crt
    fi

    echo "-> Hoàn tất keystore và truststore cho ${NODE_NAME}"
}

# Sinh cho các node trong dải lab (Cloud hoặc VMware)
create_node_cert "cass-dev1" "192.168.56.11"
create_node_cert "cass-dev2" "192.168.56.12"
create_node_cert "cass-int3" "192.168.56.13"

echo "=== [TV4] Hoàn tất toàn bộ hạ tầng chứng chỉ TLS ==="

