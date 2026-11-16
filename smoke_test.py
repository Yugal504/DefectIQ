"""End-to-end smoke test via FastAPI TestClient (no network server needed)."""
from fastapi.testclient import TestClient

from app.main import app

with TestClient(app) as c:
    # login
    r = c.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    print("LOGIN ok; role:", r.json()["user"]["role"], "perms:", r.json()["permissions"])

    # bad login
    assert c.post("/api/login", json={"username": "admin", "password": "x"}).status_code == 401

    # unauthorized
    assert c.get("/api/kpis").status_code == 401

    k = c.get("/api/kpis", headers=H).json()
    print("KPIs:", {kk: k[kk] for kk in ("total_in_smartsheet", "total_in_github", "issue_statuses_count",
          "matched_defects", "missing_in_github", "linked_to_github", "not_linked_to_github",
          "open_defects", "in_progress", "closed_defects", "unassigned_defects")})

    ch = c.get("/api/charts", headers=H).json()
    print("charts status_distribution:", ch["status_distribution"][:4])

    d = c.get("/api/defects?page=1&page_size=5&status=Open", headers=H).json()
    print("defects total(open):", d["total"], "first title:", d["items"][0]["defect_title"][:40] if d["items"] else None)

    # chat (offline)
    for q in ["How many defects are open?", "developer-wise distribution",
              "Which defects are in Smartsheet but missing in GitHub?",
              "list unassigned defects", "are there duplicate defects?"]:
        resp = c.post("/api/chat", headers=H, json={"message": q, "history": []}).json()
        print(f"CHAT  Q: {q!r:55} -> used_llm={resp['used_llm']} | {resp['reply'][:70]}")

    # CRUD
    cr = c.post("/api/defects", headers=H, json={"defect_title": "Smoke test defect", "consolidated_status": "Open", "priority": "High"})
    assert cr.status_code == 201, cr.text
    rid = cr.json()["record_id"]
    print("CREATE ok:", rid)
    up = c.put(f"/api/defects/{rid}", headers=H, json={"consolidated_status": "In Progress", "assigned_developer": "tester"})
    assert up.status_code == 200 and up.json()["consolidated_status"] == "In Progress"
    print("UPDATE ok")
    assert c.delete(f"/api/defects/{rid}", headers=H).status_code == 200
    print("DELETE ok")

    # permission enforcement: viewer cannot create
    vt = c.post("/api/login", json={"username": "viewer", "password": "viewer123"}).json()["token"]
    VH = {"Authorization": f"Bearer {vt}"}
    assert c.post("/api/defects", headers=VH, json={"defect_title": "x"}).status_code == 403
    print("RBAC ok: viewer blocked from create")

    # exports
    for url in ["/api/export/consolidated", "/api/export/kpis", "/api/export/source/github"]:
        er = c.get(url, headers=H)
        assert er.status_code == 200 and len(er.content) > 1000, url
        print(f"EXPORT ok: {url} ({len(er.content)} bytes)")

    # audit
    au = c.get("/api/audit", headers=H).json()
    print("AUDIT entries:", len(au["entries"]))

print("\nALL SMOKE TESTS PASSED")
