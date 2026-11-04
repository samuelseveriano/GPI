"""Avaliação da IA local com perguntas técnicas brasileiras (executada no GitHub Actions com o pacote real).

Mede: tempo de carga, primeiro token, tempo total, pico de RAM do processo do modelo, quantas respostas passaram pela
verificação (Camada 4), quantos trechos foram removidos (normas/certificados inventados, afirmações de liberação) e
se algum conteúdo proibido sobrou no texto final (deve ser zero). Também mede o Modo Essencial (sem LLM).

Uso: python scripts/evaluate_local_ai.py --pacote pack/ia --saida avaliacao_ia.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gpi.ai import assistant as AS          # noqa: E402
from gpi.ai.runtime import LocalLLM         # noqa: E402
from gpi.compliance.knowledge import KnowledgeBase   # noqa: E402
from gpi.db import Database                 # noqa: E402

QUESTIONS = [
    "Uma fechadura eletrônica com Wi-Fi precisa de homologação da Anatel?",
    "Uma luminária LED de 220 V precisa de certificação do Inmetro?",
    "Posso importar um carregador USB-C da China para comercialização?",
    "Um produto com Bluetooth precisa de homologação?",
    "Qual documentação preciso solicitar ao fornecedor chinês de um fone Bluetooth?",
    "Esse produto possui requisitos de ensaio no Brasil? É uma caixa de som com Bluetooth e bateria de lítio.",
    "Existe exigência de LPCO para essa mercadoria?",
    "Qual é a diferença entre certificação, homologação e anuência?",
    "Meu produto já possui uma homologação válida?",
    "Quais informações técnicas preciso obter antes de classificar esse produto na NCM?",
]


def peak_rss(pid, stop, out):
    try:
        import psutil
    except ImportError:
        return
    p = psutil.Process(pid)
    while not stop.is_set():
        try:
            out["pico_mb"] = max(out.get("pico_mb", 0), p.memory_info().rss / 1_048_576)
        except psutil.Error:
            break
        time.sleep(0.2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pacote", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "aval.sqlite")
    kb = KnowledgeBase(db, tmp)
    cfg = {"ia_modo": "ia_local", "ia_ram_mb": 4096, "ia_contexto": 4096, "ia_timeout_s": 180, "ia_threads": a.threads,
           "ia_max_tokens": 400}
    llm = LocalLLM(cfg, [Path(a.pacote)])
    t0 = time.perf_counter()
    llm.ensure_started()
    load = time.perf_counter() - t0
    mem, stop = {}, threading.Event()
    threading.Thread(target=peak_rss, args=(llm.proc.pid, stop, mem), daemon=True).start()
    rows = []
    for q in QUESTIONS:
        t = time.perf_counter()
        ess = AS.answer(q, kb, None, {**cfg, "ia_modo": "essencial"})
        t_ess = time.perf_counter() - t
        r = AS.answer(q, kb, llm, cfg)
        final = r["resposta"].lower()
        proibido = any(x in final for x in ("liberado para importar", "está liberad", "isento de", "dispensad"))
        v = r.get("verificacao") or {}
        rows.append({"pergunta": q, "modo_final": r["modo"], "aviso": r.get("aviso_ia"), "geracao": r.get("geracao"),
                     "removidos": v.get("removidos", []), "proporcao_mantida": v.get("proporcao_mantida"),
                     "conteudo_proibido_no_final": proibido, "resposta_final": r["resposta"][:1500],
                     "essencial_s": round(t_ess, 3), "fontes": [f["id"] for f in r["fontes"]]})
        print(f"[{r['modo']}] {q} — {((r.get('geracao') or {}).get('segundos'))} s, removidos {len(v.get('removidos', []))}", flush=True)
    stop.set()
    st = llm.status(verify=True)
    llm.stop()
    gens = [x["geracao"] for x in rows if x.get("geracao")]
    summary = {
        "modelo": st.get("modelo"), "manifesto": (st.get("verificacao") or {}).get("manifesto"),
        "tempo_carga_s": round(load, 2), "pico_ram_mb": round(mem.get("pico_mb", 0), 1),
        "tempo_medio_resposta_s": round(sum(g["segundos"] for g in gens) / max(1, len(gens)), 2),
        "primeiro_token_medio_s": round(sum((g.get("primeiro_token_s") or 0) for g in gens) / max(1, len(gens)), 2),
        "respostas_ia_aprovadas": sum(1 for x in rows if x["modo_final"] == "ia_local"),
        "respostas_com_fallback": sum(1 for x in rows if x["modo_final"] == "essencial"),
        "trechos_removidos_total": sum(len(x["removidos"]) for x in rows),
        "conteudo_proibido_no_final": sum(1 for x in rows if x["conteudo_proibido_no_final"]),
        "tempo_medio_modo_essencial_s": round(sum(x["essencial_s"] for x in rows) / len(rows), 3),
        "perguntas": len(rows),
    }
    out = {"resumo": summary, "respostas": rows}
    Path(a.saida).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# Avaliação da IA local", "", "| Indicador | Valor |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items()
                                                                              if not isinstance(v, dict)]
    Path(a.saida).with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if summary["conteudo_proibido_no_final"]:
        sys.exit("a verificação deixou passar conteúdo proibido")


if __name__ == "__main__":
    main()
