# GPI — Manual de utilização (v0.3)

## 1. Abrir
1. Extraia `GPI-Windows-Portable.zip` em qualquer pasta sua (ex.: `Documentos\GPI`). Não precisa instalar nada nem ser administrador.
2. Clique duas vezes em **GPI.exe**.
3. Aparece uma pequena janela **"GPI em execução"** e o navegador abre em `http://127.0.0.1:8765`.
4. Para encerrar: feche a janela "GPI em execução" (ou *Sistema → Encerrar GPI*). Os dados ficam salvos.

Na primeira abertura a sincronização começa sozinha (barra azul no topo). Enquanto isso, o painel mostra o que já existe; os resultados novos aparecem quando a análise termina. Depois, o GPI atualiza sozinho uma vez por semana enquanto estiver aberto — se ficar fechado por semanas, atualiza na próxima abertura.

Onde ficam os dados: `%LOCALAPPDATA%\GPI` (banco, logs, cache, configurações e credenciais), separados dos arquivos do programa. Para usar em pen-drive, crie um arquivo vazio `portable.flag` ao lado do GPI.exe: os dados passam a ficar na pasta `dados`.

Se o Windows ou o antivírus bloquear o GPI.exe, peça liberação à TI (veja `docs/TI.md`). O GPI não tenta contornar bloqueios.

## 2. Páginas
| Página | O que mostra |
|---|---|
| Visão Geral | Resumo: fontes ativas, produtos promissores, emergentes, mais criticados |
| Radar Global | Tendências, categorias em aceleração, comparação entre países |
| Brasil | Câmbio, sinais de demanda, importações, varejo (IBGE) |
| China | Preços médios indicativos de importação, novas categorias descobertas |
| Marketplaces | Tendências do Mercado Livre (se conectado) e estado dos demais |
| YouTube Intelligence | Vídeos de review/unboxing/comparativos por produto (requer chave) |
| Review Intelligence | Opiniões analisadas: elogios, reclamações, problemas recorrentes, exemplos com link |
| Comparador de Produtos | 2 a 4 produtos lado a lado, cada atributo com fonte e confiabilidade |
| Machine Learning / Forecasting | Previsões automáticas, modelo escolhido, qualidade, intervalos |
| Clustering | Grupos de produtos por comportamento |
| Ranking de Oportunidades | Score 0–100, cobertura, confiança, evidências e riscos; 8 rankings |
| Central de Integrações | Conectar fontes (chave, login oficial, aceite de termos) |
| Saúde das Fontes | Estado real de cada fonte, última coleta, registros, erros |
| Vendas próprias (opcional) | Importar planilhas de vendas, laboratório de previsão, ABC/XYZ, estoque |
| Metodologia | Todas as fórmulas |

Clique em qualquer série para ver o gráfico, a previsão e a **origem do dado** (fonte, URL, data de coleta, confiabilidade).

## 3. Conectar fontes (Central de Integrações)
- **Fontes públicas e feeds RSS:** já conectados.
- **YouTube:** crie uma chave gratuita no Google Cloud Console (ative "YouTube Data API v3"), cole em *YouTube → Chave de API → Conectar*. O GPI limita o uso diário (padrão 3.000 unidades).
- **Reddit:** crie um app do tipo *installed app* em reddit.com/prefs/apps, cole o Client ID e confirme que o uso é não comercial ou contratado.
- **Mercado Livre:** cadastre um app no DevCenter com a URL de redirecionamento exibida, informe App ID e Secret Key e clique em *Entrar com Mercado Livre*.
- **Google Notícias:** ative somente se os termos de uso do Google permitirem o uso na sua empresa.
- **Amazon, Shopee, AliExpress, Alibaba, Taobao, Google Trends, Trustpilot, Reclame Aqui, comparadores:** exigem aprovação/contrato; o botão leva ao site oficial para solicitar.

Use *Testar conexão* para confirmar e *Sincronizar* para coletar na hora. Credenciais ficam criptografadas com a DPAPI do Windows (só seu usuário lê). O GPI nunca pede senha de marketplace.

## 4. Como interpretar
- **Score de oportunidade** prioriza investigação; não é probabilidade de sucesso nem recomendação de compra.
- **Cobertura** = quanto do score tem dados; **confiança** = qualidade e corroboração das fontes.
- **Reclamações** são contagens de opiniões publicadas, não taxa de defeito.
- **Previsões** de interesse, importação e popularidade nunca são convertidas em unidades vendidas.

## 5. Problemas comuns
| Sintoma | O que fazer |
|---|---|
| Fontes "falhou — proxy bloqueou" | Peça à TI liberar os endereços de `docs/TI.md` |
| "certificado TLS não verificado" | A TI fornece um arquivo PEM; informe o caminho em `ca_bundle` no `config.json` da pasta de dados |
| "Arquivos do GPI ausentes ou alterados" | Extraia o ZIP novamente |
| Porta ocupada | O GPI tenta 8765–8774 automaticamente |
| Log | `%LOCALAPPDATA%\GPI\logs\gpi.log` |
