# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`. Report: `reports/eval_seeded_regression.json` sinh ở M4 (run ID dạng `E-seeded_regression-<ngày>-2791`, eval set `27910804735d`) |
| Triệu chứng | Grader Lab 8 FAIL `status resolved != denied`. Reply nói *"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."*; ledger ghi `refund_vnd=20000, refund_count=1`; nhãn là `denied`, `refund_vnd=0`. Đọc ledger trước reply: reply khớp ledger (20.000), nhưng cả hai đều sai so với nhãn, nên tiền đã ra thật |
| Bước sai đầu tiên | **Event 3 `model_override` `{"delay_days": 5}`** |
| Vì sao là bước *đầu tiên* | Event 1 `handoff`: đúng hợp đồng (`principal_scope: owner_order_only`, chỉ cho phép tool đọc). Event 2 `investigator`: đọc đúng DB, đơn O-202 `delivered`, **trễ 2 ngày**, dưới mức 3 ngày của clause SHIP-LATE-03 nên không được hoàn. Event 3: agent lấy số "trễ 5 ngày" khách tự khai trong ticket đè lên DB. Từ đây event 4 `quote` tính ra 20.000đ (`entitled`), event 5–6 chỉ là hệ quả |
| Failure mode | **FM-03** ticket_trust: tin ticket hơn DB |
| Đối chứng | `fixed C-002@11`: **không có** event `model_override`; event 3 `quote` = 0 (`no_entitlement`); event 4 reply *"chưa đủ điều kiện hoàn theo chính sách hiện hành"*; ledger 0 = nhãn; grader Lab 8 PASS |
| Regression test | `tests/test_lab9_trace_case_c002.py` (marker `student`, chạy trong CI cùng `-k "lab9 and not advanced"`): `test_seeded_regression_first_wrong_step_is_model_override` assert event 1–2 là `handoff`/`investigator` với `delay_days == 2`, event 3 là `model_override {"delay_days": 5}`, ledger 20.000 ≠ nhãn 0; `test_fixed_keeps_the_db_fact` assert không có `model_override`, ledger 0, status `denied`. **Đã chạy: 2 passed** (`python -m pytest -q -m student -o addopts= -k trace_case`). Ở mức eval, grader `db_fact_kept` (fail khi có event `model_override`) và `refund_amount_correct` (ledger ≠ nhãn) cũng bắt được trial này sau M3 |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent chọn tin ticket: MockLLM không ghi lý do, nên chỉ thấy hành vi. Trên baseline `swarm`, cùng lỗi chỉ xuất hiện ở seed 55 (seed % 5 == 0), tức 1/5 seed. Với LLM thật, tần suất có thể khác, và 5 seed không đủ để ước lượng chắc chắn. Trace cũng không cho biết lỗi có lan sang claim khác có ticket nói sai số ngày (ví dụ prompt injection ở C-009) hay không; cần chạy thêm để kiểm |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
