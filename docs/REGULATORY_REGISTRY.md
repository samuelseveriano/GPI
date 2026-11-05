# Inteligência regulatória — registros oficiais e empresas (GPI v0.8)

Página: **Conformidade → Empresas com Produtos Homologados** (`#empresas-registros`). API: `/api/regulatorio/*`.
Relatório: **Pesquisa de Homologações e Registros** (PDF, XLSX, CSV).

## Fontes verificadas (sonda no CI, 04/11/2026)

| Fonte | Resultado | Uso no GPI |
|---|---|---|
| Anatel — dados abertos `produtos_certificados.zip` | HTTP 200, 7,9 MB, **191.630 linhas**, 21 colunas oficiais | download oficial e carga completa (VALIDADO COM DADOS REAIS) |
| Anatel — consulta pública SCH | formulário (HTTP 401 para robôs) | só o link para confirmação manual |
| Inmetro — API do portal dados.gov.br (Registro de Objetos, Prodcert) | HTTP 401: exige token | não automatizado |
| Inmetro — registro.inmetro.gov.br/consulta | formulário HTML | **não é raspado**: consulta manual assistida |
| Inmetro — Prodcert | tempo esgotado | só o link |

Colunas reais da Anatel: Data da Homologação; Número de Homologação; Nome do Solicitante; CNPJ do Solicitante;
Certificado de Conformidade Técnica; Data do Certificado; Data de Validade do Certificado; Código/Situação do
Certificado; Código/Situação do Requerimento; Nome do Fabricante; Modelo; Nome Comercial; Categoria do Produto; Tipo do
Produto; IC_ANTENA; IC_ATIVO; País do Fabricante; CodUIT; CodISO.

Situações no arquivo real: Homologação Suspensa 98.601 · Emitida 80.883 · Cancelada 6.290 · Em Análise 5.582 · outras
274. **Mais da metade das homologações não está vigente.** O GPI mostra a situação e nunca trata uma homologação
suspensa como válida.

## Papéis (não confundir)

| Papel | Significado |
|---|---|
| Titular (solicitante Anatel / detentor do registro Inmetro) | requerente e titular do certificado de homologação; **não é necessariamente o fabricante** |
| Fabricante | fabricante declarado (com país) |
| Organismo certificador (OCD/OCP) | emite o certificado de conformidade; não é fabricante nem titular |

Também ficam distinguidos registro de objeto (Inmetro), certificação de conformidade, homologação (Anatel), anuência,
licenciamento e titularidade. O significado de cada campo aparece na interface e no relatório.

## Correspondência

| Classe | Critério |
|---|---|
| CORRESPONDÊNCIA EXATA | modelo técnico normalizado idêntico, com fabricante ou marca compatível (ou não informado) |
| CORRESPONDÊNCIA PROVÁVEL | mesmo modelo com outro fabricante, ou modelo informado contido no registrado (≥ 6 caracteres) |
| PRODUTO SEMELHANTE | mesmo tipo ou empresa, modelo diferente |
| SEM CORRESPONDÊNCIA CONFIRMADA | nada encontrado na base carregada (confirmar na consulta oficial) |

Quando o modelo ou o número é informado, fabricante e marca **classificam** os resultados e não os filtram. Assim, o
mesmo modelo de outro fabricante aparece como "provável" em vez de sumir.

A comparação técnica separa características coincidentes, diferentes e faltantes. Os dados abertos não publicam
potência, tensão, frequência nem componentes; essas informações ficam como "confirmar no certificado ou no relatório
de ensaio". A ferramenta nunca afirma equivalência técnica.

## Limitações (exibidas em toda pesquisa)

Um registro semelhante não comprova nada do que segue:

- dispensa de certificação;
- direito de uso do certificado de terceiro;
- autorização de comercialização;
- dispensa de LPCO ou de anuência;
- validade para outro modelo.

Quantidade de registros não é participação de mercado. Empresas encontradas não têm, necessariamente, interesse em
fornecer.

## Validação com dados reais (workflow `regulatory-data`, run 41848739182)

- Arquivo oficial carregado pelo código do aplicativo: 191.630 registros, 18 campos reconhecidos.
- Referência real **DW092 / Nikon**: correspondência EXATA. Homologação 004901402678; titular Nikon do Brasil Ltda;
  fabricante Nikon Corporation; situação **Homologação Suspensa** (exibida como não vigente). Consulta em 33 ms.
- Mesmo modelo com outro fabricante → PROVÁVEL. Modelo inexistente → sem correspondência.
- Pesquisa de empresas com registros desde 2025 (amostra limitada a 200 registros por consulta):

| Pesquisa | Registros | Titulares | Fabricantes |
|---|---|---|---|
| Carregador de celular | 200 | 44 | 41 |
| Fone de ouvido | 84 | 20 | 28 |
| Smartwatch | 178 | 10 | 9 |
| Fechadura inteligente (desde 2024) | 39 | 8 | 10 |

Exemplos reais estão no artefato `fontes-regulatorias`.

## Inmetro

**Implementado e testado com dados simulados. NÃO validado com dados reais.**

- **Importação do arquivo oficial:** o usuário baixa o arquivo no portal (o portal exige login/token) e importa em CSV.
  O cabeçalho é reconhecido por nome; colunas desconhecidas são preservadas.
- **Consulta manual assistida:** registra órgão, endereço oficial, data, número, resultado, informações e responsável.
  Endereços fora do gov.br são recusados.

## Checklist para fornecedores

É gerado pela análise de conformidade (Conformidade → Análises → Checklist) em português, inglês e chinês
simplificado. O chinês vem marcado como "revisar antes de enviar": não houve validação por tradutor humano. Exporta em
PDF e XLSX. Certificações internacionais não substituem automaticamente os requisitos brasileiros.
