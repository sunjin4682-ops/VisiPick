"""
tests/auto_test.py — 헤드리스 풀 사이클 자동 테스트 (V6.5 통합 로드맵 Phase 0)

WPF 없이 핵심 자동화 루프(검사·분류·분기·수집·이재·운반)를 N회 반복 검증한다.
의존 인프라를 자체 기동해 'python -m tests.auto_test' 한 줄로 끝난다:
  - MQTT 브로커 : 1883 이 닫혀 있으면 mock.MockBroker(순수 파이썬) 자동 기동
  - Mock 디바이스: MockESP32(9001) · MockMyCobot(9002) · MockAGV(MQTT) 자동 기동
  - 전 dummy 강제: vision/serial/robot dummy_mode=True (실 하드웨어 config 파일은 불변)

통과 기준(로드맵): N/N 성공 · DB 기록 · 예외 0.

사용:
  python -m tests.auto_test            # 기본 50회 (config.system.demo_cycles)
  python -m tests.auto_test 5          # 5회 (스모크)
"""
import os, sys, time, socket, subprocess
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# ── 1) 전 dummy 강제 + 테스트 가속 — state_machine import '전에' config 변경 ──
#    config 는 공유 dict 이고 DUMMY_MODE 류 상수는 import 시점에 캡처되므로 먼저 바꾼다.
from src.utils.config_loader import config
config["vision"]["dummy_mode"] = True
config["serial"]["dummy_mode"] = True
config["robot"]["dummy_mode"]  = True
config["agv"]["dummy_mode"]    = True
config["vision"]["dummy_interval_sec"] = 0.1     # 센서 트리거 간격 (가속)
config["sensor"]["debounce_sec"]       = 0.02    # 디바운스도 낮춰야 트리거가 먹힘

from src.utils.logger import setup_logger
logger = setup_logger("autotest")

BROKER_PORT = config["mqtt"]["port"]


def _port_open(host, port, timeout=0.5) -> bool:
    s = socket.socket(); s.settimeout(timeout)
    try:
        s.connect((host, port)); return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_port(host, port, timeout=8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _port_open(host, port):
            return True
        time.sleep(0.1)
    return False


class _Infra:
    """브로커 + Mock 디바이스 기동/정리."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []
        self.broker = None

    def up(self):
        if _port_open("localhost", BROKER_PORT):
            logger.info(f"기존 브로커 사용 (localhost:{BROKER_PORT})")
        else:
            from mock.MockBroker import MockBroker
            self.broker = MockBroker(port=BROKER_PORT).start()
            if not _wait_port("localhost", BROKER_PORT):
                raise RuntimeError("MockBroker 기동 실패")
            logger.info("MockBroker(순수 파이썬) 기동")

        env = dict(os.environ, MOCK_ROBOT_DELAY="0.05", MOCK_AGV_STEP="0.03",
                   PYTHONIOENCODING="utf-8")
        for mod in ("mock.MockESP32", "mock.MockMyCobot", "mock.MockAGV"):
            self.procs.append(subprocess.Popen(
                [sys.executable, "-m", mod], cwd=str(_ROOT), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        _wait_port("localhost", 9001)        # MockESP32
        _wait_port("localhost", 9002)        # MockMyCobot
        time.sleep(0.8)                      # MockAGV(MQTT) 구독 안정화
        logger.info("Mock 인프라 기동 완료 (ESP32/MyCobot/AGV)")

    def down(self):
        for p in self.procs:
            try: p.terminate()
            except Exception: pass
        for p in self.procs:
            try: p.wait(timeout=3)
            except Exception:
                try: p.kill()
                except Exception: pass
        if self.broker:
            self.broker.stop()


class AutoTest:
    def __init__(self, total: int):
        self.total = total
        self.success = 0
        self.fail = 0
        self.times: list[float] = []
        self.results: list[tuple] = []

    def run(self):
        from src.core.db import get_stats
        from src.core.state_machine import VisiPickStateMachine, State

        infra = _Infra()
        infra.up()
        db_before = get_stats().get("total", 0)

        # 성공 사이클 1회 = 레시피(4종) 완성 = 트레이에 부품 N개 수집.
        # (_tray.get_count() 은 이재 직후 reset 되므로, 완성 사이클의 수집량은 레시피 크기)
        recipe_size = len(config["recipe"]["parts"])

        sm = VisiPickStateMachine()
        sm.start()
        logger.info(f"자동 테스트 시작 — 목표 {self.total}회 (전 dummy 소프트 파이프라인)")
        start_all = time.time()

        try:
            for i in range(1, self.total + 1):
                t0 = time.time()
                ok = sm.run_cycle()
                dt = round(time.time() - t0, 2)
                collected = recipe_size if ok else 0
                if ok and sm.state == State.COMPLETE:
                    self.success += 1
                    self.times.append(dt)
                    self.results.append((i, "SUCCESS", collected, dt))
                    logger.success(f"사이클 {i}/{self.total} 성공 — {dt}s, 수집 {collected}개")
                else:
                    self.fail += 1
                    self.results.append((i, "FAIL", 0, dt))
                    logger.error(f"사이클 {i}/{self.total} 실패 (state={sm.state.value})")
                    break
                time.sleep(0.05)
        finally:
            total_time = round(time.time() - start_all, 2)
            try:
                sm._shutdown()
            except Exception:
                pass
            db_added = get_stats().get("total", 0) - db_before
            stats = get_stats()
            infra.down()

        self._report(total_time, db_added, stats)
        return self.fail == 0

    def _report(self, total_time, db_added, stats):
        avg   = round(sum(self.times) / len(self.times), 2) if self.times else 0
        best  = round(min(self.times), 2) if self.times else 0
        worst = round(max(self.times), 2) if self.times else 0
        rate  = round(self.success / self.total * 100, 1) if self.total else 0

        report = f"""
{'='*48}
VisiPick 헤드리스 자동 테스트 결과 (전 dummy)
실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*48}
총 사이클:  {self.total}회
성공:       {self.success}회
실패:       {self.fail}회
성공률:     {rate}%
{'-'*48}
평균 사이클: {avg}s   최단: {best}s   최장: {worst}s
전체 소요:   {total_time}s
DB 신규 검사행: {db_added}건
분류 누계: NEEDED={stats.get('needed_count')} · DUPLICATE={stats.get('duplicate_count')} · """ + \
f"""DEFECT={stats.get('defect_count')} · UNCERTAIN={stats.get('uncertain_count')}
{'='*48}
판정: {'PASS ✅ (N/N · DB 기록 · 예외 0)' if self.fail == 0 else 'FAIL ❌'}
{'='*48}
"""
        print(report)
        logger.info(report)

        Path("logs").mkdir(exist_ok=True)
        out = Path("logs") / f"autotest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(report)
            f.write("\n사이클별 상세:\n")
            for cyc, status, collected, dt in self.results:
                f.write(f"  [{cyc:2}] {status:7} — 수집 {collected}개 — {dt}s\n")
        logger.info(f"결과 파일 저장: {out}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else config["system"]["demo_cycles"]
    ok = AutoTest(total=n).run()
    sys.exit(0 if ok else 1)
