from pathlib import Path
from openpyxl import load_workbook

p = Path(r"C:\Users\224175\OneDrive - NTT DATA, Inc\Desktop\Data_extraction\downloads\Cockpit_Issue_Tracker.xlsx")
wb = load_workbook(p, data_only=True)
print("Sheets:", wb.sheetnames)
for ws in wb.worksheets:
    print(f"\n[{ws.title}] max_row={ws.max_row} (data rows={ws.max_row-1})")
    for r in range(2, min(ws.max_row, 6) + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, 6)]
        print(f"  row{r}: {vals}")
wb.close()
