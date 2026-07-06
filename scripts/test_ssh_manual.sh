#!/usr/bin/env bash
set -u

HOST="${NOMI_SSH_HOST:-206.119.171.141}"
USER="${NOMI_SSH_USER:-root}"
PORTS_RAW="${NOMI_SSH_PORTS:-22 10799}"

read -r -a PORTS <<<"$PORTS_RAW"

echo "== Nomi SSH connectivity diagnostic =="
echo "host: $HOST"
echo "user: $USER"
echo "ports: ${PORTS[*]}"
echo

echo "== 1. Current public IPv4 =="
curl -4 -sS --connect-timeout 5 --max-time 10 https://api.ipify.org || true
echo
echo

echo "== 2. Route to server =="
route get "$HOST" 2>/dev/null || true
echo

echo "== 3. TCP port reachability =="
for port in "${PORTS[@]}"; do
  echo "-- port $port --"
  nc -vz -w 5 "$HOST" "$port" || true
done
echo

echo "== 4. SSH host key scan =="
for port in "${PORTS[@]}"; do
  echo "-- ssh-keyscan port $port --"
  ssh-keyscan -T 8 -p "$port" "$HOST" 2>&1 | sed -n '1,20p' || true
done
echo

echo "== 5. Remove local known_hosts entries for this host =="
ssh-keygen -R "$HOST" || true
for port in "${PORTS[@]}"; do
  ssh-keygen -R "[$HOST]:$port" || true
done
echo

echo "== 6. SSH verbose handshake tests =="
echo "If SSH reaches password authentication, enter the server password manually."
echo "If it fails before password prompt with kex_exchange_identification or Connection reset/closed, it is not a password or known_hosts problem."
echo

for port in "${PORTS[@]}"; do
  echo "=============================="
  echo "Testing SSH port $port"
  echo "=============================="

  ssh \
    -4 \
    -p "$port" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o GlobalKnownHostsFile=/dev/null \
    -o ConnectTimeout=12 \
    -vvv \
    "$USER@$HOST" \
    'echo SSH_LOGIN_OK && hostnamectl && uname -a' 2>&1 | sed -n '1,180p'

  echo
done
