"""Validação REAL (CI, sem segredos) da pesquisa direcionada do Product Research — revisão do PR #18.

Sobe o GPI num banco VAZIO (o produto não existe no SQLite), executa uma pesquisa completa e registra o que cada fonte
realmente fez. Sem credenciais, só o GDELT (público) pode ser consultado de verdade; as demais devem aparecer como
"não autorizada" com o motivo concreto — nunca como sucesso. Falha se:
  * alguma fonte sem credencial for marcada como consultada com dados;
  * o GDELT devolver erro de FORMATO (mudança na API);
  * a pesquisa sem evidências não for marcada como "dados insuficientes".
Rede indisponível/limite do GDELT é registrado e não reprova (não é defeito do GPI)."""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(out_path: str) -> int:
    import uvicorn

    from gpi.app import create_app
    tmp = Path(tempfile.mkdtemp())
    app = create_app(tmp / "data", ROOT / "frontend")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.1)

    def req(path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                   method="POST" if body is not None else "GET", headers={"Content-Type": "application/json", "X-GPI": "1"})
        with urllib.request.urlopen(r, timeout=600) as resp:
            return json.loads(resp.read())
    report = {"produtos": [], "falhas": []}
    try:
        for q in ("carregador GaN 65W", "robot vacuum cleaner"):
            before = req("/api/suite/visao")["produtos"]
            r = req("/api/suite/pesquisa", {"consulta": q, "profundidade": "completa", "mercado": "BR", "comparacao": ["US"], "sincrono": True})
            j = req(f"/api/suite/pesquisa/{r['id']}")
            res = j["result"]
            col = (res.get("coleta") or {}).get("resultados", [])
            item = {"consulta": q, "nome_comercial": res["abas"]["visao_geral"].get("produto"), "status": j["status"], "mensagem": res.get("mensagem_final"),
                    "decisao": res["decisao"]["cor"], "cobertura": res.get("cobertura"), "catalogo_antes": before["cadastrados"],
                    "fontes": [{k: c.get(k) for k in ("id", "mercado", "estado", "registros", "motivo", "consulta_realizada")} for c in col]}
            report["produtos"].append(item)
            for c in col:
                if c["id"] != "gdelt" and c["estado"] in ("com dados", "cache válido"):
                    report["falhas"].append(f"{q}: {c['id']} marcado com dados sem credencial")
                if c["id"] != "gdelt" and c["estado"] not in ("não autorizada", "ignorada (modo rápido)", "não cobre o mercado"):
                    report["falhas"].append(f"{q}: {c['id']} deveria ser 'não autorizada' sem credencial (veio {c['estado']})")
                if c["id"] == "gdelt" and c["estado"] == "falhou" and "formato" in (c.get("motivo") or "").lower():
                    report["falhas"].append(f"{q}: GDELT mudou o formato: {c['motivo']}")
            gd = next((c for c in col if c["id"] == "gdelt"), None)
            useful = (res.get("cobertura") or {}).get("fontes_com_evidencia", 0)
            if res["decisao"]["cor"] != "CINZA":
                report["falhas"].append(f"{q}: sem volume/anúncios a decisão deveria ser CINZA (veio {res['decisao']['cor']})")
            if not useful and res.get("mensagem_final", "").startswith("Processamento concluído — dados insuficientes") is False:
                report["falhas"].append(f"{q}: pesquisa sem evidência não marcada como dados insuficientes")
            cv = res.get("coberturas") or {}
            item["coberturas"] = {k: (cv.get(k) or {}).get("nivel") for k in ("comercial", "contextual", "tecnica")}
            if gd and gd["estado"] not in ("com dados", "sem dados", "limite de requisições", "bloqueada pela rede", "indisponível"):
                report["falhas"].append(f"{q}: GDELT com estado inesperado {gd['estado']} ({gd.get('motivo')})")
            if (cv.get("comercial") or {}).get("n"):
                report["falhas"].append(f"{q}: cobertura comercial sem nenhuma fonte comercial autorizada")
            print(f"{q}: coberturas {item['coberturas']} · confiança {(cv.get('confianca') or {}).get('nivel')}")
            print(f"{q}: {item['nome_comercial']} · {j['status']} · GDELT={gd and gd['estado']} ({gd and gd['registros']} meses) · "
                  f"fontes úteis={useful} · {res.get('mensagem_final')}")
            for c in col:
                print(f"   - {c['id']:<20} {c['mercado']:<7} {c['estado']:<24} {c['registros']:>4}  {(c.get('motivo') or '')[:110]}")
    finally:
        srv.should_exit = True
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in report["falhas"]:
        print("FALHA:", f)
    return 1 if report["falhas"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "pesquisa_direcionada_real.json"))
