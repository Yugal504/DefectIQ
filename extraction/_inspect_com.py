import win32com.client as win32
import pythoncom
from pathlib import Path

master = Path(r"C:\Users\224175\OneDrive - NTT DATA, Inc\Desktop\Data_extraction\downloads\Cockpit_Issue_Tracker.xlsm")
pythoncom.CoInitialize()
excel = win32.DispatchEx("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(str(master))
try:
    print("MultiUserEditing (shared):", wb.MultiUserEditing)
    try:
        print("ProtectStructure:", wb.ProtectStructure)
    except Exception as e:
        print("ProtectStructure err:", e)

    ws = wb.Worksheets("Smart Sheet Export")
    print("\nSmart Sheet Export:")
    print("  ProtectContents:", ws.ProtectContents, "ProtectionMode:", ws.ProtectionMode)
    for test_row in (783, 1000):
        try:
            ws.Cells(test_row, 1).Value = "TEST"
            print(f"  write Cells({test_row},1) OK; now clearing")
            ws.Cells(test_row, 1).ClearContents()
        except Exception as e:
            print(f"  write Cells({test_row},1) FAILED: {e}")

    try:
        lo = ws.ListObjects(1)
        print("  trying ListRows.Add ...")
        nr = lo.ListRows.Add()
        print("  ListRows.Add OK; deleting it")
        nr.Delete()
    except Exception as e:
        print("  ListRows.Add FAILED:", e)
finally:
    wb.Close(SaveChanges=False)
    excel.Quit()
    pythoncom.CoUninitialize()
