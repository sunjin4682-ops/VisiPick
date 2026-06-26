"""카메라 진단 — 인덱스별로 프레임이 실제로 들어오는지, 밝기는 얼마인지 확인.
실행: python tools/camtest.py 1      (인덱스 지정, 기본 1)
창이 뜨면 'q' 로 종료."""
import cv2, sys

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
print(f"=== 카메라 인덱스 {idx} 진단 (DSHOW, 자동 노출) ===")
cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
print("opened:", cap.isOpened())

# MJPG 압축 포맷 강제 — 두 카메라 USB 대역폭 공존의 핵심 (YUY2 비압축은 대역폭 폭증)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
# 장치에 눌러붙은 수동 저노출 복구 — 자동 노출 강제 ON
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)   # DSHOW: 0.75=자동
cap.set(cv2.CAP_PROP_AUTO_WB, 1)
fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
print(f"포맷: {chr(fourcc&255)}{chr((fourcc>>8)&255)}{chr((fourcc>>16)&255)}{chr((fourcc>>24)&255)} "
      f"{int(cap.get(3))}x{int(cap.get(4))} @ {cap.get(cv2.CAP_PROP_FPS):.0f}fps")

got = 0
for i in range(60):
    ok, f = cap.read()
    if ok:
        got += 1
        if got <= 3 or got % 20 == 0:
            print(f"frame {i}: shape={f.shape} 평균밝기={f.mean():.1f}")
        cv2.imshow(f"camtest idx={idx} (q=quit)", f)
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            break
    else:
        print(f"frame {i}: read 실패")

print(f"\n총 {got}/60 프레임 수신.")
if got == 0:
    print("→ 이 인덱스는 프레임을 못 줍니다. 다른 인덱스(0/2) 시도하거나 점유 프로그램 확인.")
cap.release()
cv2.destroyAllWindows()
