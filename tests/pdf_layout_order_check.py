from app.rag.file_parser import _order_lines_by_layout


def run() -> None:
    # Simulate two-column physical layout: left column should be read before right column.
    lines = [
        {"text": "L1", "top": 10.0, "x0": 40.0, "x1": 180.0, "x_center": 110.0},
        {"text": "R1", "top": 12.0, "x0": 340.0, "x1": 500.0, "x_center": 420.0},
        {"text": "L2", "top": 22.0, "x0": 45.0, "x1": 185.0, "x_center": 115.0},
        {"text": "R2", "top": 24.0, "x0": 345.0, "x1": 505.0, "x_center": 425.0},
        {"text": "L3", "top": 34.0, "x0": 48.0, "x1": 188.0, "x_center": 118.0},
        {"text": "R3", "top": 36.0, "x0": 348.0, "x1": 508.0, "x_center": 428.0},
        {"text": "L4", "top": 46.0, "x0": 44.0, "x1": 184.0, "x_center": 114.0},
        {"text": "R4", "top": 48.0, "x0": 344.0, "x1": 504.0, "x_center": 424.0},
        {"text": "L5", "top": 58.0, "x0": 42.0, "x1": 182.0, "x_center": 112.0},
        {"text": "R5", "top": 60.0, "x0": 342.0, "x1": 502.0, "x_center": 422.0},
        {"text": "L6", "top": 70.0, "x0": 41.0, "x1": 181.0, "x_center": 111.0},
        {"text": "R6", "top": 72.0, "x0": 341.0, "x1": 501.0, "x_center": 421.0},
    ]
    ordered = _order_lines_by_layout(lines, page_width=600.0)
    assert ordered[:6] == ["L1", "L2", "L3", "L4", "L5", "L6"]
    assert ordered[6:] == ["R1", "R2", "R3", "R4", "R5", "R6"]


if __name__ == "__main__":
    run()
