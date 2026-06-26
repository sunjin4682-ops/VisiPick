"""두 카메라 동시 열기 테스트 — USB 대역폭 공존 확인.
상부(0)+측면(1)을 MJPG 로 동시에 열어 둘 다 프레임이 들어오는지 본다.
실행: python tools/camtest_dual.py
두 창이 다 컬러로 뜨면 MJPG 로 공존 성공. 한쪽만 검으면 대역폭/컨트롤러 분리 필요.
'q' 로 종료."""
import cv2

TOP_IDX, SIDE_IDX = 0, 1


def open_mjpg(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    # 순서 중요: FOURCC(MJPG) 를 해상도보다 먼저 — DSHOW 에서 이래야 압축 포맷이 적용됨
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    f = int(cap.get(cv2.CAP_PROP_FOURCC))
    fmt = f"{chr(f&255)}{chr((f>>8)&255)}{chr((f>>16)&255)}{chr((f>>24)&255)}"
    print(f"  idx={idx}: opened={cap.isOpened()} 포맷={fmt} "
          f"{int(cap.get(3))}x{int(cap.get(4))}")
    return cap


print("=== 상부(0)+측면(1) 동시 열기 (MJPG) ===")
top  = open_mjpg(TOP_IDX)
side = open_mjpg(SIDE_IDX)

print("\n워밍업(자동 노출 수렴) 중...")
for _ in range(30):
    top.read(); side.read()

# 두 창을 떼어놓는다 — 기본값이면 둘 다 (0,0) 에 겹쳐 떠서 한쪽이 가려짐
cv2.namedWindow("TOP idx=0", cv2.WINDOW_NORMAL)
cv2.namedWindow("SIDE idx=1", cv2.WINDOW_NORMAL)
cv2.moveWindow("TOP idx=0", 50, 50)
cv2.moveWindow("SIDE idx=1", 750, 50)

for i in range(120):
    ok_t, ft = top.read()
    ok_s, fs = side.read()
    if i % 30 == 0:
        bt = ft.mean() if ok_t else -1
        bs = fs.mean() if ok_s else -1
        print(f"[{i:3d}] 상부 ok={ok_t} 밝기={bt:6.1f} | 측면 ok={ok_s} 밝기={bs:6.1f}")
    if ok_t:
        cv2.imshow("TOP idx=0", ft)
    if ok_s:
        cv2.imshow("SIDE idx=1", fs)
    if (cv2.waitKey(1) & 0xFF) == ord("q"):
        break

print("\n판정: 두 창 모두 컬러(밝기 100+)면 MJPG 동시 공존 성공.")
print("      측면이 검정(밝기 0~10)이면 → USB 대역폭 부족, 컨트롤러 분리 필요.")
top.release(); side.release()
cv2.destroyAllWindows()
