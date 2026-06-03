"""
mock/MockBroker.py — 최소 MQTT 3.1.1 브로커 (테스트 전용, 순수 파이썬)

mosquitto / docker 없이 헤드리스 테스트(tests/auto_test, C2 라운드트립)를 돌리기
위한 초경량 브로커. VisiPick 내부 통신은 전부 QoS0(paho 기본값)이므로
QoS0 PUBLISH/SUBSCRIBE + 와일드카드(+, #) 매칭만 구현한다.

⚠️ 운영용 아님 — 인증·QoS1/2·retain·persistent session 없음. 로컬 테스트 전용.

단독 실행:           python -m mock.MockBroker      (포트 1883)
프로그램에서 기동:    from mock.MockBroker import MockBroker
                     b = MockBroker(); b.start()   # 백그라운드 스레드
                     ...
                     b.stop()
"""
import socket, struct, threading, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger

logger = setup_logger("mockbroker")

# 패킷 타입 (고정 헤더 상위 4비트)
CONNECT, CONNACK, PUBLISH = 1, 2, 3
SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK = 8, 9, 10, 11
PINGREQ, PINGRESP, DISCONNECT = 12, 13, 14


def _topic_matches(filter_parts: list[str], topic_parts: list[str]) -> bool:
    """MQTT 토픽 필터 매칭 (+ 단일 레벨, # 멀티 레벨)."""
    for i, f in enumerate(filter_parts):
        if f == "#":
            return True                      # 나머지 전부 (부모 레벨도) 매칭
        if i >= len(topic_parts):
            return False
        if f != "+" and f != topic_parts[i]:
            return False
    return len(filter_parts) == len(topic_parts)


def _encode_remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n % 128
        n //= 128
        if n > 0:
            byte |= 0x80
        out.append(byte)
        if n == 0:
            return bytes(out)


class _Client:
    __slots__ = ("sock", "send_lock", "subs")

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.send_lock = threading.Lock()
        self.subs: list[list[str]] = []      # 구독 필터를 '/'로 미리 분할해 저장

    def send(self, data: bytes) -> bool:
        try:
            with self.send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            return False


class MockBroker:
    def __init__(self, host: str = "0.0.0.0", port: int = 1883):
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._clients: list[_Client] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ── 수신 헬퍼: 정확히 n바이트 읽기 (TCP 스트림 → 패킷 경계 복원) ──────
    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _read_remaining_length(self, sock: socket.socket) -> int | None:
        multiplier, value = 1, 0
        for _ in range(4):
            b = self._recv_exact(sock, 1)
            if b is None:
                return None
            value += (b[0] & 0x7F) * multiplier
            if not (b[0] & 0x80):
                return value
            multiplier *= 128
        return None

    # ── 발행 → 매칭 구독자에게 팬아웃 ─────────────────────────────────────
    def _fanout(self, topic: str, payload: bytes):
        tparts = topic.split("/")
        vh = struct.pack("!H", len(topic.encode())) + topic.encode() + payload
        pkt = bytes([PUBLISH << 4]) + _encode_remaining_length(len(vh)) + vh
        with self._lock:
            targets = [c for c in self._clients
                       if any(_topic_matches(f, tparts) for f in c.subs)]
        for c in targets:
            c.send(pkt)

    # ── 클라이언트 1개 처리 ───────────────────────────────────────────────
    def _handle(self, sock: socket.socket, addr):
        client = _Client(sock)
        with self._lock:
            self._clients.append(client)
        try:
            while not self._stop.is_set():
                hdr = self._recv_exact(sock, 1)
                if hdr is None:
                    break
                ptype = hdr[0] >> 4
                flags = hdr[0] & 0x0F
                rem = self._read_remaining_length(sock)
                if rem is None:
                    break
                body = self._recv_exact(sock, rem) if rem else b""
                if body is None:
                    break

                if ptype == CONNECT:
                    client.send(bytes([CONNACK << 4, 0x02, 0x00, 0x00]))
                elif ptype == PINGREQ:
                    client.send(bytes([PINGRESP << 4, 0x00]))
                elif ptype == SUBSCRIBE:
                    self._on_subscribe(client, body)
                elif ptype == UNSUBSCRIBE:
                    client.send(bytes([UNSUBACK << 4, 0x02]) + body[0:2])
                elif ptype == PUBLISH:
                    self._on_publish(client, flags, body)
                elif ptype == DISCONNECT:
                    break
                # 그 외 타입은 무시
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)
            try:
                sock.close()
            except OSError:
                pass

    def _on_subscribe(self, client: _Client, body: bytes):
        pkt_id = body[0:2]
        idx, granted = 2, bytearray()
        while idx + 2 <= len(body):
            tlen = struct.unpack("!H", body[idx:idx + 2])[0]
            idx += 2
            topic = body[idx:idx + tlen].decode("utf-8", "replace")
            idx += tlen + 1                  # +1: requested QoS 바이트 스킵
            client.subs.append(topic.split("/"))
            granted.append(0x00)             # 항상 QoS0 승인
        client.send(bytes([SUBACK << 4]) +
                    _encode_remaining_length(2 + len(granted)) + pkt_id + bytes(granted))

    def _on_publish(self, client: _Client, flags: int, body: bytes):
        tlen = struct.unpack("!H", body[0:2])[0]
        topic = body[2:2 + tlen].decode("utf-8", "replace")
        idx = 2 + tlen
        qos = (flags >> 1) & 0x03
        if qos > 0:                          # QoS1/2: 패킷 ID 스킵(+ QoS1 PUBACK)
            pkt_id = body[idx:idx + 2]
            idx += 2
            if qos == 1:
                client.send(bytes([0x40, 0x02]) + pkt_id)
        payload = body[idx:]
        self._fanout(topic, payload)

    # ── 라이프사이클 ──────────────────────────────────────────────────────
    def start(self) -> "MockBroker":
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(16)
        self._server.settimeout(0.5)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        logger.info(f"MockBroker 시작 — {self.host}:{self.port} (테스트용 QoS0 브로커)")
        return self

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        with self._lock:
            for c in list(self._clients):
                try:
                    c.sock.close()
                except OSError:
                    pass
            self._clients.clear()
        logger.info("MockBroker 종료")


if __name__ == "__main__":
    broker = MockBroker(port=1883).start()
    logger.info("Ctrl+C 로 종료")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        broker.stop()
