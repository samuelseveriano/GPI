# Changelog

## 0.9.1 — Product Intelligence Suite (2026-11)

Somente ferramentas gratuitas; nenhuma dependência paga obrigatória.

### Adicionado
- **Pesquisa de Produtos**: pesquisa por nome (pt/en), mercado, mercados de comparação, período (3/6/12/24 meses ou
  personalizado), objetivo e profundidade; 11 etapas reais com progresso gravado; dossiê com Visão geral, Demanda,
  Marketplaces, Produtos semelhantes, Fornecedores, Importação, Qualidade, Previsões e Evidências; salvar, histórico,
  exportação XLSX/PDF; "Investigar Produto" no dossiê.
- **Classificação da decisão** VERDE/AMARELO/VERMELHO/CINZA sobre os estágios da v0.9 (falta de dado = CINZA, nunca VERMELHO).
- **Registro de evidências** rastreável (`research_evidence`) sem dupla contagem.
- **Explorador de Nichos**, **Palavras-chave** (observadas × geradas; volume só de fonte autorizada; hipóteses por anúncio),
  **Inteligência de Marketplaces** (anúncio por nome/URL/ID, comparação de 5, histórico de preço real, tendências,
  avaliações coletadas e por arquivo).
- **Pesquisa por Imagem** local: JPG/PNG/WEBP, colar, arrastar, URL pública (com proteção SSRF), recorte, catálogo visual,
  6 classes de correspondência, embeddings ONNX opcionais, links de busca reversa assistida (Lens/TinEye/Yandex).
- **Inteligência de Fornecedores**: empresas canônicas, aliases, normalização (inclui sufixos chineses), fila de
  duplicidades com decisão humana, importação CSV/XLSX validada, embarques com deduplicação, relações
  documentadas/declaradas/inferidas/incertas, relações gratuitas a partir de Anatel/Inmetro, descoberta por produto,
  avaliação documental × declarada × do usuário, correspondência preliminar produto↔fornecedor.
- **ImportYeti** opcional com controle de créditos (bloqueado por padrão).
- **Investigação de Importação**: NCM candidata, estatísticas agregadas do Comex Stat, regulatório preliminar, riscos e
  simulador (FOB, frete por unidade, custos, custo total, margem, markup; cenários Conservador/Base/Otimista; pendências).
- **Monitorados** (produtos e fornecedores) atualizados na sincronização existente; **Provedores e custos**.
- Interface: 10 páginas em "Inteligência de Consumo" (o "Radar de Candidatos" passou para lá como "Radar Comercial"),
  cartões no Dashboard e atalhos no Dossiê.

### Alterado
- `requirements.txt` declara Pillow explicitamente (já vinha com o ReportLab).
- `tests/test_v05.py` passa a verificar as rotas dos módulos `v09*.js`.

### Banco de dados
- Apenas tabelas novas, criadas sob demanda; nenhuma tabela existente alterada. Cadastro antigo de fornecedores copiado.
