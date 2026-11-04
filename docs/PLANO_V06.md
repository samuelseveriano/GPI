# GPI v0.6 — auditoria da v0.5 e plano de migração

## 1. Auditoria (início da v0.6, 03/11/2026)

| Item | Situação encontrada |
|---|---|
| Branches | `main` ainda na Fase 3 (47e47c4). `fase4` e `feature/gpi-v0.5` **não foram incorporadas** (nenhum PR aberto: o token do GitHub do ambiente de desenvolvimento não permite criar PR). A v0.6 parte de `feature/gpi-v0.5` (86a0cab), que contém a fase 4. |
| Testes | 162 aprovados, 7 ignorados localmente (bibliotecas opcionais só no CI do Windows). |
| Banco | SQLite com migrações v1–v5, só aditivas. |
| Conectores v0.5 | Mercado Livre Trends, Google Trends BigQuery, Google Ads, Microsoft Advertising, eBay: implementados, **não validados** (exigem credenciais do usuário). GDELT validado com coleta real (com HTTP 429 a partir do GitHub). |
| Relatórios | Só exportação simples (CSV/XLSX de uma tabela) das fases 1–2. Sem PDF. |
| Redes sociais | YouTube (chave de API, página própria) e Reddit (menções) desde a fase 3. Sem TikTok, Instagram ou Facebook. |

## 2. Plano executado (ordem da especificação)

1. **Centro de Relatórios** — `backend/gpi/reports/` (dados → XLSX/PDF/CSV), histórico com snapshot para reprodução, exportação por página, relatório semanal opcional. Migração v6 (tabela `reports`).
2. **Fontes de pesquisa** — validação real no CI (job 2) e relatórios gerados com os dados reais coletados.
3. **TikTok** — Discovery API (hashtags populares, termos de busca em alta, termos recomendados) com OAuth assistido.
4. **Meta** — Central Meta (um login, três conectores: Instagram hashtags, Facebook páginas, Biblioteca de Anúncios).
5. **Social Intelligence** — `backend/gpi/social/analysis.py`: séries por plataforma, normalização por plataforma, Social Trend Score, Viral Product Radar, Search vs. Social; Opportunity Engine 3.0.
6. **Machine Learning** — `forecasting/social_ablation.py`: comparação com × sem sinais sociais, regra de adoção.
7. **Testes e build** — `tests/test_v06.py`, smoke test do executável com exportação XLSX/PDF, pacote `GPI-Windows-Portable-v0.6.zip`.

## 3. Migração de dados

* Migração v6 só **cria** tabelas (`reports`, `social_observations`, `social_quota`). Nenhum dado existente é alterado.
* Bancos das versões anteriores abrem normalmente (teste `test_migration_v6_preserves_existing_database`).
* Relatórios ficam em `%LOCALAPPDATA%\GPI\relatorios\AAAA\`, ao lado de um snapshot compactado dos dados usados.

## 4. Dependências novas

| Biblioteca | Uso | Licença | Impacto |
|---|---|---|---|
| ReportLab ≥ 4 | PDF | BSD | ~4 MB no pacote; Python puro com aceleradores opcionais |
| Fonte DejaVu Sans (regular e negrito) | Acentuação no PDF | Bitstream Vera + domínio público (redistribuível) | 1,4 MB |
| pdfplumber, pypdf | Somente testes | MIT / BSD | não entram no pacote |

Excel continua com openpyxl (já incluído). Nenhum serviço externo, Office ou LibreOffice é necessário.
