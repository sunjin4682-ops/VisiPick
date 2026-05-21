import time
from datetime import datetime
from src.core.state_machine import VisiPickStateMachine, State
from src.utils.logger import setup_logger

logger = setup_logger("autotest")

class AutoTest:
    def __init__(self, total=50):
        self.total      = total
        self.success    = 0
        self.fail       = 0
        self.times      = []
        self.results    = []

    def run(self):
        logger.info(f"자동 테스트 시작 — 목표: {self.total}회")
        start_all = time.time()

        for i in range(1, self.total + 1):
            logger.info(f"\n{'='*40}")
            logger.info(f"사이클 {i}/{self.total}")

            sm = VisiPickStateMachine()
            start = time.time()

            try:
                sm.phase1_inspect()
                sm.phase2_robot()
                sm.phase3_agv()

                elapsed = round(time.time() - start, 2)
                self.times.append(elapsed)
                self.success += 1
                self.results.append({
                    "cycle": i,
                    "status": "SUCCESS",
                    "class": sm.current_class,
                    "time": elapsed
                })
                logger.success(f"사이클 {i} 성공 — {elapsed}초 ({sm.current_class}클래스)")

            except Exception as e:
                self.fail += 1
                self.results.append({
                    "cycle": i,
                    "status": "FAIL",
                    "class": None,
                    "time": 0
                })
                logger.error(f"사이클 {i} 실패 — {e}")

        total_time = round(time.time() - start_all, 2)
        self._report(total_time)

    def _report(self, total_time):
        avg  = round(sum(self.times) / len(self.times), 2) if self.times else 0
        best = round(min(self.times), 2) if self.times else 0
        worst= round(max(self.times), 2) if self.times else 0
        rate = round(self.success / self.total * 100, 1)

        report = f"""
{'='*40}
자동 테스트 결과 보고서
실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*40}
총 사이클:  {self.total}회
성공:       {self.success}회
실패:       {self.fail}회
성공률:     {rate}%
{'='*40}
평균 사이클 시간: {avg}초
최단 사이클 시간: {best}초
최장 사이클 시간: {worst}초
전체 소요 시간:   {total_time}초
{'='*40}
"""
        print(report)
        logger.info(report)

        # 결과 파일 저장
        with open(f"logs/autotest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt", "w", encoding="utf-8") as f:
            f.write(report)
            f.write("\n사이클별 상세:\n")
            for r in self.results:
                f.write(f"  [{r['cycle']:2}] {r['status']} — {r['class']}클래스 — {r['time']}초\n")

        logger.info("결과 파일 저장 완료")

if __name__ == "__main__":
    test = AutoTest(total=50)
    test.run()
