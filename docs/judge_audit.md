# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

```
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10
n=100 P=0.857 R=0.8 kappa=0.757 {'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}
fail rate observed 0.28 -> corrected 0.3
PASS floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}

python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10
n=100 P=1.0 R=0.3 kappa=0.375 {'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}
fail rate observed 0.09 -> corrected 0.3
FAIL floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}
```

FAIL là lớp dương (việc của judge là *tìm* lỗi). Judge chạy ở chế độ replay: phán quyết có sẵn trong CSV, không gọi model.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt cả 3 | **dùng** |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Trượt κ (0.375 < 0.6) và R (0.3 < 0.7) | **loại** |

Ma trận nhầm lẫn:

| | Người FAIL | Người PASS |
|---|---|---|
| **tone_ok**: judge FAIL | tp = 24 | fp = 4 |
| **tone_ok**: judge PASS | fn = 6 | tn = 66 |
| **helpful**: judge FAIL | tp = 9 | fp = 0 |
| **helpful**: judge PASS | fn = **21** | tn = 70 |

## ≥5 case audit thủ công

Toàn bộ 10 ca bất đồng của `tone_ok` (6 fn, 4 fp). "Ai đúng" được quyết bằng cách đọc nguyên văn câu trả lời và cột `note` trong `data/eval/judge_tone_public.csv`.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú (sửa rubric) |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách; judge coi là thân thiện. **Rubric:** bắt buộc xưng "LogiX" / "anh/chị", liệt kê cách xưng hô bị cấm ("em… nha", "bạn ơi") |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." | PASS | FAIL | Người | Gọi khách là "bạn". **Rubric:** như #1 |
| 3 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Giọng ra lệnh, chặn khách liên hệ; judge chỉ thấy "Dạ, vui lòng". **Rubric:** FAIL khi câu trả lời ngăn khách phản hồi, dù có từ lịch sự |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý; judge phạt vì thiếu lời xin lỗi. **Rubric:** xin lỗi *không bắt buộc* khi yêu cầu đã được giải quyết |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | CS LogiX cho phép từ "refund"; judge phạt vì tiếng Anh. **Rubric:** thêm danh sách từ tiếng Anh được phép |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải giọng điệu, nên giao cho grader code `reply_matches_ledger` (FM-08). **Rubric:** ghi rõ judge tone không chấm cam kết về tiền |
| 7 | H-070 "Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. **Rubric:** cấm emoji trong phản hồi khiếu nại |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Người gán nhãn đọc nhầm ticket. **Hành động:** sửa nhãn người thành FAIL, không sửa rubric |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ cho đơn O-233 ạ." | FAIL | PASS | Người (còn tranh cãi) | Lặp "Dạ" do lỗi gõ. **Rubric:** lỗi gõ nhỏ không làm FAIL tiêu chí giọng điệu |
| 10 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | Người | Dịch máy, mất dấu tiếng Việt. **Rubric:** FAIL khi câu trả lời mất dấu |

Tổng kết 10 ca: người đúng 9/10, judge đúng 1/10 (H-081, sửa nhãn).

Lỗi của judge `tone_ok` gom thành 3 nhóm, đều sửa được bằng rubric:
- bỏ lọt cách xưng hô suồng sã và giọng ra lệnh (#1, #2, #3, #7, #10);
- phạt oan vì thiếu lời xin lỗi hoặc dùng từ được phép (#4, #5, #9);
- chấm lấn sang nội dung về tiền (#6), phần này phải để code chấm.

Mẫu bất đồng của `helpful` (21 fn, 0 fp):

| Case | Câu trả lời | Note của người | Vì sao judge bỏ lọt |
|---|---|---|---|
| HL-015 | "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | ledger ghi 40.000đ | Judge không thấy ledger, câu nghe đủ ý |
| HL-020 | "Dạ, LogiX đã hoàn 90.000đ cho đơn O-303 ạ." | ledger ghi 120.000đ | như trên |
| HL-016, HL-028, HL-035… | câu dài, xin lỗi nhiều lần, số tiền sai | ledger ghi số khác | Lời xin lỗi dày đặc làm judge chấm "hữu ích" |
| HL-047, HL-091, HL-097 | "Ok bạn, đơn O-515 xử lý rồi nhé." | (không có số tiền, không nói kết quả) | Câu cụt, không cho khách biết đã hoàn bao nhiêu |

## Kết luận

- **`tone_ok`: dùng được** làm tiêu chí phụ (không chặn release một mình). κ = 0.757, P = 0.857, R = 0.800, cả 3 qua ngưỡng. Tỉ lệ lỗi giọng điệu quan sát 28%, sau hiệu chỉnh Rogan-Gladen là 30%: judge hơi đếm thiếu, nhưng không lệch nhiều.
- **`helpful`: loại, không được dùng làm gate.**
  - Precision = 1.0 nhìn rất tốt, nhưng Recall chỉ 0.3: trong 30 câu người đánh FAIL, judge chỉ bắt được 9 và **bỏ sót 21** (fn = 21).
  - κ = 0.375 < 0.6, tức đồng thuận với người chỉ ở mức yếu.
  - Nếu dùng judge này làm gate, ta sẽ báo tỉ lệ lỗi 9% trong khi thực tế khoảng **30%** (Rogan-Gladen 0.09 → 0.30). Gate sẽ cho qua phần lớn bản lỗi.
- **Vì sao `helpful` hỏng:** gần như mọi ca bị sót là câu trả lời **nói sai số tiền so với ledger**. Judge chỉ đọc chữ, không đọc ledger, nên câu trả lời càng lễ phép, xin lỗi càng nhiều thì càng dễ lọt. Đây đúng là FM-08 (misreport). Lỗi này phải chấm bằng code: grader `reply_matches_ledger` so số tiền trong câu trả lời với ledger.
- **Nguyên tắc rút ra:** tiền và phê duyệt luôn chấm bằng code. Judge chỉ dùng cho tiêu chí không có đáp án chính xác (giọng điệu), và chỉ sau khi đã qua κ ≥ 0.6, P ≥ 0.8, R ≥ 0.7.
- **Rủi ro còn lại:**
  - Judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí), chưa có tập held-out mới. Rubric đã sửa ở trên cần một bộ nhãn người mới để đo lại.
  - 1/10 ca bất đồng do chính nhãn người sai (H-081), nên nhãn người cũng cần kiểm chéo (2 người gán nhãn).
  - Với LLM thật, phán quyết của judge có thể dao động giữa các lần chạy; replay không đo được điều này.
