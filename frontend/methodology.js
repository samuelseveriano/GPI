/* Página "Metodologia e Fórmulas" — descreve exatamente o que o código calcula.
   Cada fórmula corresponde a uma função em backend/gpi (indicada em "Código"). */
window.METHODOLOGY = function () {
  const F = (t) => `<div class="formula">${tex(t)}</div>`;
  const code = (p) => `<p class="muted">Código: <code>${p}</code></p>`;
  return `
<div class="method">
<h1>Metodologia e fórmulas</h1>
<p class="sub">Tudo o que o GPI calcula está descrito aqui, com as mesmas fórmulas usadas no código. Nenhum resultado é gerado por números aleatórios ou por serviços externos: os cálculos rodam neste computador.</p>

<div class="panel"><h2>Sumário</h2><ol class="toc">
<li><a href="#m-fluxo">Fluxo de cálculo</a></li><li><a href="#m-serie">Construção da série</a></li>
<li><a href="#m-ref">Modelos de referência</a></li><li><a href="#m-ets">Suavização exponencial (ETS)</a></li>
<li><a href="#m-int">Demanda intermitente</a></li><li><a href="#m-pi">Intervalos de previsão</a></li>
<li><a href="#m-bt">Backtesting e métricas</a></li><li><a href="#m-tend">Tendência e sazonalidade</a></li>
<li><a href="#m-abc">ABC, XYZ e padrão de demanda</a></li><li><a href="#m-est">Estoque e reposição</a></li>
<li><a href="#m-lim">Limitações</a></li><li><a href="#m-ref2">Referências</a></li>
<li><a href="#m-col">Coleta autônoma e proveniência</a></li><li><a href="#m-desc">Descoberta, normalização e deduplicação</a></li>
<li><a href="#m-der">Séries derivadas</a></li><li><a href="#m-auto">AutoML de séries temporais</a></li>
<li><a href="#m-opp">Score de oportunidade</a></li><li><a href="#m-clu">Clusterização</a></li>
<li><a href="#m-nlp">Opiniões (NLP) e conteúdo</a></li><li><a href="#m-ml3">Modelos opcionais e tipos de previsão</a></li></ol></div>

<div class="panel" id="m-fluxo"><h2>1. Fluxo de cálculo</h2>
<ol>
<li><b>Importação</b>: cada linha é validada (data, quantidade ≥ 0, SKU). Linhas inválidas são rejeitadas e listadas — nunca corrigidas por suposição.</li>
<li><b>Série temporal</b>: as vendas são somadas por semana ou mês (seção 2).</li>
<li><b>Backtesting</b>: cada modelo é reajustado em várias datas passadas usando só os dados anteriores a elas, e seus erros são medidos nos períodos seguintes (seção 7).</li>
<li><b>Seleção</b>: o modelo com menor erro fora da amostra (WAPE por padrão) é sugerido. O Naive é sempre incluído como referência mínima.</li>
<li><b>Previsão final</b>: o modelo é reajustado com todo o histórico e produz previsão pontual e intervalos de 80% e 95% (seção 6).</li>
<li><b>Estoque</b>: o erro medido no backtesting alimenta o estoque de segurança e o ponto de reposição (seção 10).</li>
</ol></div>

<div class="panel" id="m-serie"><h2>2. Construção da série</h2>
${F('y_{t} = \\sum_{i \\in t} q_{i}')}
<p>onde <i>q<sub>i</sub></i> é a quantidade de cada venda registrada no período <i>t</i> (semana ISO segunda–domingo, ou mês civil).</p>
<ul>
<li><b>Períodos sem registro</b> entre a primeira e a última venda do SKU valem 0 somente com a premissa “sem registro = sem venda” ativada (padrão). Se desativada, séries com lacunas são recusadas; o sistema nunca interpola valores.</li>
<li><b>Períodos incompletos</b>: se os dados terminam antes do fim do último período (ex.: dados até 12/03 e série mensal), esse período é descartado, pois somaria apenas parte das vendas e puxaria a previsão para baixo. O mesmo vale para o primeiro período.</li>
</ul>${code('backend/gpi/series.py · build_series')}</div>

<div class="panel" id="m-ref"><h2>3. Modelos de referência</h2>
<h3>Naive</h3>${F('\\hat{y}_{T+h|T} = y_{T}')}
<h3>Naive sazonal</h3>${F('\\hat{y}_{T+h|T} = y_{T+h-m(k+1)}, \\quad k = \\lfloor (h-1)/m \\rfloor')}
<p><i>m</i> = 12 (mensal) ou 52 (semanal).</p>
<h3>Média móvel (k = 3)</h3>${F('\\hat{y}_{T+h|T} = \\frac{1}{k} \\sum_{i=0}^{k-1} y_{T-i}')}
${code('backend/gpi/forecasting/models.py · naive, seasonal_naive, moving_average')}</div>

<div class="panel" id="m-ets"><h2>4. Suavização exponencial — ETS aditivo</h2>
<p>Forma de correção de erros (Hyndman et al., 2008). Com <i>e<sub>t</sub></i> = erro um-passo-à-frente:</p>
${F('\\hat{y}_{t|t-1} = \\ell_{t-1} + \\phi b_{t-1} + s_{t-m}')}
${F('e_{t} = y_{t} - \\hat{y}_{t|t-1}')}
${F('\\ell_{t} = \\ell_{t-1} + \\phi b_{t-1} + \\alpha e_{t}')}
${F('b_{t} = \\phi b_{t-1} + \\beta e_{t}')}
${F('s_{t} = s_{t-m} + \\gamma e_{t}')}
<p>Previsão:</p>
${F('\\hat{y}_{T+h|T} = \\ell_{T} + (\\phi + \\phi^{2} + \\cdots + \\phi^{h}) b_{T} + s_{T+h-m(k+1)}')}
<table><tr><th>Código</th><th>Modelo</th><th>Componentes</th></tr>
<tr><td>ETS(A,N,N)</td><td>Suavização exponencial simples</td><td>só nível (β = γ = 0)</td></tr>
<tr><td>ETS(A,A,N)</td><td>Holt</td><td>nível + tendência, φ = 1</td></tr>
<tr><td>ETS(A,Ad,N)</td><td>Holt amortecido</td><td>tendência amortecida, 0,8 ≤ φ ≤ 0,98</td></tr>
<tr><td>ETS(A,N,A)</td><td>Nível + sazonalidade</td><td>s com Σs = 0</td></tr>
<tr><td>ETS(A,A,A)</td><td>Holt-Winters aditivo</td><td>nível + tendência + sazonalidade</td></tr>
<tr><td>ETS(A,Ad,A)</td><td>Holt-Winters amortecido</td><td>idem, com φ</td></tr></table>
<h3>Estimação</h3>
<p>Os parâmetros minimizam a soma dos quadrados dos erros um-passo-à-frente (equivalente à máxima verossimilhança gaussiana), com L-BFGS-B:</p>
${F('\\min_{\\alpha,\\beta,\\gamma,\\phi,\\ell_{0},b_{0},s_{0}} \\; \\mathrm{SSE} = \\sum_{t=1}^{n} e_{t}^{2}')}
<p>Restrições: 0 &lt; α &lt; 1, 0 &lt; β &lt; α, 0 &lt; γ &lt; 1 − α, Σ<i>s</i> = 0. Os estados sazonais iniciais são otimizados quando <i>m</i> ≤ 13; em séries semanais (<i>m</i> = 52) usam a inicialização heurística (regressão linear nos primeiros ciclos + média dos resíduos por posição).</p>
<h3>Seleção automática (ETS automático)</h3>
${F('\\mathrm{AICc} = n \\ln\\left(\\frac{\\mathrm{SSE}}{n}\\right) + 2p + \\frac{2p(p+1)}{n-p-1}')}
<p><i>p</i> = parâmetros de suavização + estados iniciais (ℓ<sub>0</sub>, b<sub>0</sub>, m−1 sazonais) + σ. Vence a especificação de menor AICc, escolhida apenas com os dados de treino.</p>
${code('backend/gpi/forecasting/models.py · ets, ets_auto')}</div>

<div class="panel" id="m-int"><h2>5. Demanda intermitente</h2>
<h3>Croston com correção SBA</h3>
<p>Atualizado só nos períodos com demanda (<i>q</i> = períodos desde a última demanda):</p>
${F('z_{t} = z_{t-1} + \\alpha (y_{t} - z_{t-1}), \\quad p_{t} = p_{t-1} + \\alpha (q - p_{t-1})')}
${F('\\hat{y}_{T+h|T} = \\left(1 - \\frac{\\alpha}{2}\\right) \\frac{z_{T}}{p_{T}}')}
<h3>TSB (Teunter–Syntetos–Babai)</h3>
<p>A probabilidade de ocorrência <i>d</i> é atualizada em todo período, o que permite à previsão cair quando o item para de vender:</p>
${F('d_{t} = d_{t-1} + \\beta (\\mathbb{1}[y_{t}>0] - d_{t-1})')}
${F('\\hat{y}_{T+h|T} = d_{T} \\cdot z_{T}')}
<p>α e β são escolhidos em uma grade {0,05; 0,1; 0,15; 0,2; 0,3} pelo menor erro quadrático um-passo-à-frente.</p>
${code('backend/gpi/forecasting/models.py · croston, tsb')}</div>

<div class="panel" id="m-pi"><h2>6. Intervalos de previsão</h2>
${F('\\hat{y}_{T+h|T} \\pm z_{(1+c)/2} \\sqrt{\\mathrm{Var}(h)}, \\quad z_{0.90} = 1.2816, \\; z_{0.975} = 1.9600')}
<p>O limite inferior é truncado em 0 (vendas não são negativas). Variância por modelo:</p>
<table><tr><th>Modelo</th><th>Var(h)</th><th>Tipo</th></tr>
<tr><td>Naive</td><td>${tex('h \\sigma^{2}', false)}</td><td>analítica</td></tr>
<tr><td>Naive sazonal</td><td>${tex('(k+1) \\sigma^{2}', false)}</td><td>analítica</td></tr>
<tr><td>ETS (todos)</td><td>${tex('\\sigma^{2} \\left[1 + \\sum_{j=1}^{h-1} c_{j}^{2}\\right], \\; c_{j} = \\alpha + \\beta(\\phi + \\cdots + \\phi^{j}) + \\gamma \\mathbb{1}[j \\bmod m = 0]', false)}</td><td>analítica (classe 1)</td></tr>
<tr><td>Média móvel</td><td>${tex('\\sigma^{2}(1 + 1/k)', false)}</td><td>aproximada</td></tr>
<tr><td>Croston-SBA, TSB</td><td>${tex('\\sigma^{2}', false)}</td><td>aproximada</td></tr></table>
${F('\\hat{\\sigma}^{2} = \\frac{1}{n - p} \\sum_{t} e_{t}^{2}')}
<p>Intervalos “aproximados” podem ter cobertura real diferente da nominal. Por isso o backtesting mede a <b>cobertura empírica</b> do intervalo de 80%: valores muito abaixo de 80% indicam intervalos estreitos demais.</p>
${code('backend/gpi/forecasting/backtest.py · interval')}</div>

<div class="panel" id="m-bt"><h2>7. Backtesting e métricas</h2>
<p><b>Origem móvel com janela expansiva</b>: para cada origem <i>T<sub>i</sub></i>, o modelo é ajustado (parâmetros e escolha por AICc incluídos) apenas com <i>y</i><sub>1</sub>…<i>y</i><sub>T<sub>i</sub></sub> e prevê <i>h</i> = 1…H. Os erros vêm só de dados que o modelo não viu — isso evita vazamento de dados (data leakage). As origens são consecutivas, terminando em <i>n</i> − H para que todo o horizonte seja observado.</p>
${F('e_{i,h} = \\hat{y}_{T_{i}+h|T_{i}} - y_{T_{i}+h}')}
${F('\\mathrm{MAE} = \\frac{1}{N} \\sum |e_{i,h}| \\qquad \\mathrm{RMSE} = \\sqrt{\\frac{1}{N} \\sum e_{i,h}^{2}}')}
${F('\\mathrm{WAPE} = \\frac{\\sum |e_{i,h}|}{\\sum |y_{T_{i}+h}|}')}
${F('\\mathrm{Bias} = \\frac{1}{N} \\sum e_{i,h} \\qquad \\mathrm{Bias\\%} = \\frac{\\sum e_{i,h}}{\\sum y_{T_{i}+h}}')}
<p>Bias positivo = superestimação (risco de excesso); negativo = subestimação (risco de ruptura).</p>
${F('\\mathrm{RMSSE}_{i} = \\sqrt{\\frac{\\frac{1}{H} \\sum_{h} e_{i,h}^{2}}{\\frac{1}{T_{i}-1} \\sum_{t=2}^{T_{i}} (y_{t} - y_{t-1})^{2}}}')}
<p>RMSSE &lt; 1: o modelo erra menos que um Naive um-passo dentro do treino. É comparável entre SKUs de escalas diferentes (usado na competição M5). O valor reportado é a média sobre as origens.</p>
${F('\\mathrm{Cobertura}_{80} = \\frac{1}{N} \\sum \\mathbb{1}[L_{i,h} \\le y_{T_{i}+h} \\le U_{i,h}]')}
${F('\\mathrm{FVA} = 1 - \\frac{\\mathrm{WAPE}_{\\text{modelo}}}{\\mathrm{WAPE}_{\\text{Naive}}}')}
<p><b>FVA</b> (valor agregado da previsão): positivo significa que o modelo supera o Naive. Se nenhum modelo tiver FVA positivo, a recomendação honesta é usar o Naive — modelos mais complexos não são considerados superiores sem evidência.</p>
${code('backend/gpi/forecasting/backtest.py · backtest, metrics')}</div>

<div class="panel" id="m-tend"><h2>8. Tendência e sazonalidade</h2>
<h3>Inclinação de Theil–Sen (robusta a outliers)</h3>
${F('\\beta_{TS} = \\mathrm{median}\\left\\{ \\frac{y_{j} - y_{i}}{j - i} : i < j \\right\\}')}
<p>Inclinação relativa = β<sub>TS</sub> / ȳ (variação por período em % da média). Intervalo de 95% pelo método de Sen.</p>
<h3>Teste de Mann–Kendall</h3>
${F('S = \\sum_{i<j} \\mathrm{sign}(y_{j} - y_{i}), \\qquad \\tau = \\frac{S}{n(n-1)/2}')}
<p>A tendência é declarada <b>significativa</b> apenas se o p-valor do τ de Kendall for &lt; 0,05. Caso contrário, a série é “estável” — mesmo que a inclinação estimada não seja zero.</p>
<h3>Força da sazonalidade</h3>
${F('F_{S} = \\max\\left(0, \\; 1 - \\frac{\\mathrm{Var}(R_{t})}{\\mathrm{Var}(S_{t} + R_{t})}\\right)')}
<p>Decomposição clássica aditiva (média móvel centrada 2×m). F<sub>S</sub> próximo de 1 = sazonalidade forte. Requer ao menos 2 ciclos completos.</p>
<p>Em séries curtas F<sub>S</sub> tende a ser alto mesmo sem sazonalidade real (poucas observações por mês do ano). Por isso a sazonalidade só é declarada <b>significativa</b> quando o teste de Kruskal–Wallis entre as posições do ciclo, aplicado à série sem tendência, tem p &lt; 0,05:</p>
${F('H = \\frac{12}{N(N+1)} \\sum_{j=1}^{m} \\frac{R_{j}^{2}}{n_{j}} - 3(N+1)')}
<p><i>R<sub>j</sub></i> = soma dos postos da posição <i>j</i> do ciclo; sob ausência de sazonalidade, <i>H</i> ∼ χ² com m − 1 graus de liberdade.</p>
${code('backend/gpi/analytics/classification.py · trend_test, seasonality_strength')}</div>

<div class="panel" id="m-abc"><h2>9. ABC, XYZ e padrão de demanda</h2>
<h3>ABC (Pareto)</h3>
${F('P_{i} = \\frac{v_{i}}{\\sum_{j} v_{j}}, \\qquad C_{i} = \\sum_{j \\le i} P_{j}')}
<p>Itens ordenados por valor <i>v</i> (receita = quantidade × preço; ou quantidade, sem preço). A: participação acumulada antes do item &lt; 80%; B: &lt; 95%; C: restante. Janela: últimos N períodos completos.</p>
<h3>XYZ (variabilidade)</h3>
${F('\\mathrm{CV} = \\frac{s}{\\bar{y}}')}
<p>X: CV ≤ 0,5 · Y: 0,5 &lt; CV ≤ 1,0 · Z: CV &gt; 1,0.</p>
<h3>Syntetos–Boylan–Croston</h3>
${F('\\mathrm{ADI} = \\frac{n_{\\text{períodos}}}{n_{\\text{períodos com demanda}}}, \\qquad \\mathrm{CV}^{2} = \\left(\\frac{s_{y>0}}{\\bar{y}_{y>0}}\\right)^{2}')}
<table><tr><th></th><th>CV² &lt; 0,49</th><th>CV² ≥ 0,49</th></tr>
<tr><th>ADI &lt; 1,32</th><td>suave → ETS</td><td>errática → ETS</td></tr>
<tr><th>ADI ≥ 1,32</th><td>intermitente → Croston/TSB</td><td>irregular (lumpy) → Croston/TSB</td></tr></table>
${code('backend/gpi/analytics/classification.py · abc, xyz_class, sbc')}</div>

<div class="panel" id="m-est"><h2>10. Estoque e reposição</h2>
<p>Períodos: <i>L</i> = lead time / dias por período; <i>R</i> = intervalo de revisão / dias por período (7 ou 30,44). σ<sub>d</sub> = RMSE do backtesting do modelo escolhido.</p>
<h3>Estoque de segurança</h3>
${F('SS = z_{\\text{NS}} \\sqrt{L \\sigma_{d}^{2} + \\bar{d}^{2} \\sigma_{L}^{2}}')}
<p>z<sub>NS</sub> = quantil normal do nível de serviço de ciclo (ex.: 95% → 1,645). σ<sub>L</sub> = desvio do lead time em períodos (0 se desconhecido).</p>
<h3>Ponto de reposição (revisão contínua)</h3>
${F('\\mathrm{ROP} = \\sum_{t=1}^{L} \\hat{y}_{T+t} + SS')}
<h3>Nível-alvo e quantidade (revisão periódica)</h3>
${F('S = \\sum_{t=1}^{L+R} \\hat{y}_{T+t} + z_{\\text{NS}} \\sqrt{(L+R) \\sigma_{d}^{2} + \\bar{d}^{2} \\sigma_{L}^{2}}')}
${F('Q = \\max(0, \\; S - E_{\\text{mão}} - E_{\\text{trânsito}})')}
<p>Q é arredondado para cima ao múltiplo de compra e elevado ao MOQ se necessário (o aumento por MOQ é sinalizado, pois gera excesso).</p>
<h3>Lote econômico (EOQ)</h3>
${F('\\mathrm{EOQ} = \\sqrt{\\frac{2 D K}{i \\, c}}')}
<p>D = demanda anual estimada, K = custo por pedido, i = taxa anual de manutenção, c = custo unitário. Válido para demanda aproximadamente estável.</p>
${code('backend/gpi/supply_chain/inventory.py · plan')}</div>

<div class="panel" id="m-lim"><h2>11. Limitações e uso responsável</h2>
<ul>
<li>Previsões são estimativas condicionadas ao histórico; mudanças de preço, rupturas passadas (vendas perdidas) e promoções não registradas distorcem o resultado. Vendas registradas ≠ demanda real quando houve falta de estoque.</li>
<li>A premissa normal dos intervalos e do estoque de segurança é uma aproximação; confira a cobertura empírica no backtesting.</li>
<li>Popularidade de mercado (buscas, rankings) não é demanda efetiva — esses indicadores entrarão em fases futuras e serão exibidos separadamente.</li>
<li>Recomendações de compra exigem aprovação humana. O sistema nunca realiza compras.</li>
</ul></div>

<div class="panel" id="m-ref2"><h2>12. Referências</h2>
<ul>
<li>Hyndman, R.J.; Koehler, A.B.; Ord, J.K.; Snyder, R.D. <i>Forecasting with Exponential Smoothing: The State Space Approach</i>. Springer, 2008.</li>
<li>Hyndman, R.J.; Athanasopoulos, G. <i>Forecasting: Principles and Practice</i>, 3ª ed. OTexts, 2021.</li>
<li>Croston, J.D. Forecasting and stock control for intermittent demands. <i>Operational Research Quarterly</i>, 1972.</li>
<li>Syntetos, A.A.; Boylan, J.E. The accuracy of intermittent demand estimates. <i>International Journal of Forecasting</i>, 2005.</li>
<li>Teunter, R.H.; Syntetos, A.A.; Babai, M.Z. Intermittent demand: linking forecasting to inventory obsolescence. <i>EJOR</i>, 2011.</li>
<li>Makridakis, S.; Spiliotis, E.; Assimakopoulos, V. The M5 accuracy competition. <i>IJF</i>, 2022.</li>
<li>Sen, P.K. Estimates of the regression coefficient based on Kendall's tau. <i>JASA</i>, 1968.</li>
<li>Silver, E.A.; Pyke, D.F.; Thomas, D.J. <i>Inventory and Production Management in Supply Chains</i>, 4ª ed. CRC, 2017.</li>
</ul></div>

<div class="panel" id="m-col"><h2>13. Coleta autônoma e proveniência</h2>
<p>Ao abrir o programa (e a cada semana enquanto ele estiver aberto) o gerenciador de sincronização executa, para cada fonte, os <b>jobs</b> que estiverem vencidos. Cada job tem uma chave idempotente (ex.: <code>comexstat:china:2024</code>):</p>
<ul><li>Anos/meses fechados são coletados uma vez; os dois anos mais recentes são revisitados semanalmente para captar dados novos e <b>revisões</b> da fonte (o número de revisões fica registrado em cada observação).</li>
<li>Uma observação é identificada por (série, data de referência): repetir a coleta nunca duplica dados.</li>
<li>Falhas: novas tentativas com espera exponencial e variação aleatória (<i>jitter</i>); HTTP 429 respeita o cabeçalho Retry-After; o job com falha é reagendado em 1 h, 2 h, 4 h … até 24 h. Uma fonte com falha não interrompe as demais.</li>
<li>Jobs interrompidos (programa fechado no meio) são retomados na abertura seguinte.</li>
<li>Uma fonte só é marcada como <b>funcional</b> depois de uma coleta real cujos dados passaram na validação de formato.</li></ul>
${F('\\text{espera}_{k} = \\min(60, \; 2 \\cdot 2^{k-1}) \\cdot (1 + U), \\quad U \\sim \\text{Uniforme}(0; 0,25)')}
<table><tr><th>Tipo de dado</th><th>Significado</th></tr><tr><td>Histórico observado</td><td>valor publicado pela fonte</td></tr><tr><td>Estimado por terceiros</td><td>estimativa publicada por outra organização</td></tr><tr><td>Série derivada</td><td>calculada pelo GPI a partir de séries observadas (seção 15)</td></tr><tr><td>Projeção do sistema</td><td>previsão do AutoML (seção 16)</td></tr></table>
<p>Confiabilidade: <b>A</b> estatística oficial (Comex Stat, BCB, IBGE, UN Comtrade); <b>B</b> dados abertos de plataforma com contagem direta (Wikimedia, Mercado Livre); <b>C</b> estimativa de terceiros.</p>
<p class="muted">Código: <code>backend/gpi/market/sync.py</code>, <code>backend/gpi/connectors/</code></p></div>

<div class="panel" id="m-desc"><h2>14. Descoberta, normalização e deduplicação</h2>
<p><b>Descoberta.</b> Não há lista fixa de produtos: o Comex Stat é consultado para <i>todas</i> as posições SH4 importadas pelo Brasil. São consideradas as posições com importações da China ≥ US$ 1 milhão nos últimos 12 meses; fora das categorias prioritárias, entram as que crescem mais de 30% em 12 meses e somam ≥ US$ 5 milhões. Os conceitos de produto iniciais (Wikipédia) servem de ponte para o interesse do público; seus nomes em português e chinês vêm dos links interlínguas da própria Wikipédia.</p>
<p><b>Normalização</b> (pt/en): remoção de acentos, minúsculas, remoção de palavras vazias e redução de plural por regras (ões→ão, ais→al, eis→el, ns→m, res→r, s→∅, ies→y). Texto chinês é representado por bigramas de caracteres.</p>
${F('\\text{sim}(a, b) = \\frac{1}{2} \\left( \\frac{|T_{a} \\cap T_{b}|}{|T_{a} \\cup T_{b}|} + \\frac{2 |G_{a} \\cap G_{b}|}{|G_{a}| + |G_{b}|} \\right)')}
<p><i>T</i> = conjunto de tokens normalizados (Jaccard); <i>G</i> = trigramas de caracteres (Dice). Nomes com sim ≥ 0,72 (ou nome normalizado idêntico) são tratados como o mesmo produto (ligação simples).</p>
<p class="muted">Código: <code>backend/gpi/market/taxonomy.py</code>, <code>intel.py · discover</code></p></div>

<div class="panel" id="m-der"><h2>15. Séries derivadas</h2>
${F('\\text{Participação da China}_{t} = \\frac{\\text{FOB}_{\\text{China},t}}{\\text{FOB}_{\\text{total},t}} \\qquad \\text{Preço indicativo}_{t} = \\frac{\\text{FOB}_{\\text{China},t}}{\\text{kg}_{\\text{China},t}}')}
${F('\\text{PTAX média mensal}_{m} = \\frac{1}{|D_{m}|} \\sum_{d \\in D_{m}} \\text{PTAX}_{d}')}
${F('g_{12} = \\frac{\\sum_{i=0}^{11} y_{T-i}}{\\sum_{i=12}^{23} y_{T-i}} - 1, \\qquad g_{6} = \\frac{\\sum_{i=0}^{5} y_{T-i}}{\\sum_{i=12}^{17} y_{T-i}} - 1, \\qquad \\text{aceleração} = g_{6} - g_{12}')}
<p>O preço indicativo é um valor médio por quilo de toda a posição SH4 — não é cotação de fornecedor. Meses ausentes nunca são preenchidos: a análise usa o trecho mensal contínuo mais recente.</p></div>

<div class="panel" id="m-auto"><h2>16. AutoML de séries temporais</h2>
<ol><li><b>Perfil</b>: tamanho, fração de zeros, padrão Syntetos–Boylan (seção 9), tendência de Mann–Kendall (seção 8) e sazonalidade significativa (Kruskal–Wallis).</li>
<li><b>Elegibilidade</b>: menos de 12 meses contínuos → somente análise exploratória (sem previsão quantitativa).</li>
<li><b>Candidatos</b>: intermitente → Naive, média móvel, Croston-SBA, TSB; demais → Naive, SES, Holt amortecido, Naive sazonal; Holt-Winters se a sazonalidade for significativa; Random Forest e HistGradientBoosting se houver ≥ 60 meses.</li>
<li><b>Backtesting</b> com 4 origens e horizonte de 12 meses (seção 7). Escolha do menor WAPE; se o escolhido não superar o Naive (FVA ≤ 0), fica o Naive.</li>
<li><b>Qualidade</b>: boa (WAPE &lt; 20%), moderada (&lt; 40%), baixa (≥ 40%).</li>
<li>Retreino apenas quando os dados da série mudam (hash). Previsões antigas são preservadas e avaliadas contra os valores que se realizaram.</li></ol>
<h3>Modelos de machine learning (formulação em razão ao nível recente)</h3>
${F('\\ell_{t} = \\frac{1}{L} \\sum_{i=1}^{L} y_{t-i}, \\qquad x_{t} = \\left( \\frac{y_{t-1}}{\\ell_{t}} - 1, \\ldots, \\frac{y_{t-L}}{\\ell_{t}} - 1, \; \\sin\\frac{2\\pi t}{m}, \; \\cos\\frac{2\\pi t}{m} \\right)')}
${F('\\hat{y}_{t} = \\ell_{t} \\left(1 + f(x_{t})\\right)')}
<p>L = 12 (mensal); f = Random Forest (100 árvores) ou HistGradientBoosting. Previsão recursiva. Variância aproximada σ²·h, com σ medido nos erros um-passo de um bloco final de 20% reservado (o modelo é treinado sem ele).</p>
<p><b>Tipos de previsão nunca se misturam:</b> interesse de pesquisa (visualizações) ≠ indicador de mercado (US$ importados) ≠ vendas da empresa. Um índice de interesse nunca é convertido em unidades vendidas.</p>
<p class="muted">Código: <code>backend/gpi/market/automl.py</code>, <code>backend/gpi/forecasting/ml.py</code></p></div>

<div class="panel" id="m-opp"><h2>17. Score de oportunidade (0–100)</h2>
${F('\\text{Score} = 100 \\cdot \\frac{\\sum_{c \\in C} w_{c} \\, s_{c}}{\\sum_{c \\in C} w_{c}}, \\qquad C = \\{c : s_{c} \\text{ disponível}\\}, \\quad s_{c} \\in [0, 1]')}
<table><tr><th>Componente</th><th class="num">Peso</th><th>Cálculo de s<sub>c</sub></th></tr>
<tr><td>Crescimento de interesse</td><td class="num">17%</td><td>percentil de g<sub>12</sub> das visualizações (Wikipédia em português; inglês se não houver)</td></tr>
<tr><td>Persistência da tendência</td><td class="num">13%</td><td>0,7 × fração dos últimos 12 meses acima do mesmo mês do ano anterior + 0,3 × (tendência de alta significativa)</td></tr>
<tr><td>Evidência de demanda</td><td class="num">20%</td><td>média dos percentis de g<sub>12</sub> e do nível das importações da China (próprias ou das posições SH4 relacionadas)</td></tr>
<tr><td>Menções</td><td class="num">6%</td><td>percentil do volume de menções em 12 meses (RSS, Google Notícias, Reddit)</td></tr>
<tr><td>Sentimento das opiniões</td><td class="num">8%</td><td>(saldo + 1)/2, saldo = (positivas − negativas)/total; só com ≥ 5 opiniões</td></tr>
<tr><td>Problemas recorrentes</td><td class="num">6%</td><td>1 − 2 × fração de opiniões negativas dirigidas ao produto (não à entrega/vendedor)</td></tr>
<tr><td>Concorrência observável</td><td class="num">8%</td><td>1 − percentil do nível × participação da China</td></tr>
<tr><td>Sazonalidade</td><td class="num">4%</td><td>1 − 0,5 × F<sub>S</sub> (apenas se significativa)</td></tr>
<tr><td>Volatilidade</td><td class="num">8%</td><td>1 − percentil do desvio-padrão dos log-retornos mensais</td></tr>
<tr><td>Risco comercial</td><td class="num">5%</td><td>média de 1 − 2·max(0, alta do preço US$/kg em 12m) e 1 − 3·max(0, alta do CNY/BRL em 12m)</td></tr>
<tr><td>Qualidade dos dados</td><td class="num">5%</td><td>min(1, meses de histórico / 60)</td></tr></table>
<p>Percentis são calculados entre os produtos analisados (posição relativa, não valor absoluto). O score é uma <b>classificação heurística</b> para priorizar investigação; <b>não é probabilidade de sucesso</b> e não substitui a estimativa de custos, margem, demanda e risco.</p>
<p class="muted">Código: <code>backend/gpi/market/intel.py · opportunity, rankings</code></p></div>

<div class="panel" id="m-clu"><h2>18. Clusterização</h2>
<p>Variáveis por produto: g<sub>12</sub>, aceleração, inclinação relativa de Theil–Sen (36 meses), sazonalidade, volatilidade, persistência e percentil do nível <i>dentro do mesmo tipo de sinal</i> (US$ e visualizações não são comparados diretamente). Padronização robusta (mediana e intervalo interquartil) após limitar valores ao 1º–99º percentil.</p>
${F('k^{*} = \\arg\\max_{3 \\le k \\le 8} \; \\bar{s}(k), \\qquad s(i) = \\frac{b(i) - a(i)}{\\max(a(i), b(i))}')}
<p>K-Means com k escolhido pela silhueta média; Aglomerativo (Ward) com o mesmo k, e o índice de Rand ajustado (ARI) entre ambos mede a estabilidade; HDBSCAN como verificação sem k fixo (pontos de ruído informados); PCA em 2 componentes para o mapa; Isolation Forest marca os 5% mais atípicos.</p>
<table><tr><th>Rótulo</th><th>Regra (avaliada nesta ordem)</th></tr>
<tr><td>Tendência emergente</td><td>g<sub>12</sub> &gt; 50% e nível abaixo da mediana</td></tr>
<tr><td>Crescimento acelerado</td><td>g<sub>12</sub> &gt; 25% e aceleração &gt; 5 p.p.</td></tr>
<tr><td>Possível declínio</td><td>tendência de queda significativa ou g<sub>12</sub> &lt; −15%</td></tr>
<tr><td>Crescimento estável</td><td>tendência de alta significativa</td></tr>
<tr><td>Alta sazonalidade</td><td>F<sub>S</sub> ≥ 0,6 e significativa</td></tr>
<tr><td>Alta volatilidade</td><td>desvio dos log-retornos &gt; 35%</td></tr>
<tr><td>Oportunidade de nicho</td><td>g<sub>12</sub> &gt; 10% e nível no terço inferior</td></tr>
<tr><td>Mercado maduro</td><td>nenhuma das anteriores</td></tr></table>
<p>Cada cluster recebe o nome do rótulo mais frequente entre seus membros; a composição completa e o centróide mediano são exibidos.</p>
<p class="muted">Código: <code>backend/gpi/market/intel.py · label, clusterize</code></p></div>

<div class="panel" id="m-nlp"><h2>19. Opiniões (NLP local), conteúdo e cobertura do score</h2>
<p><b>Sentimento por léxico com regras</b> (português e inglês, sem modelo externo). Para cada frase, soma-se o peso das palavras (positivas +1 a +3, negativas −1 a −3) com ajustes:</p>
${F('S = \\sum_{i} w_{i} \\cdot m_{i} \\cdot n_{i} \\cdot c_{i}, \\qquad s = \\frac{S}{\\sqrt{S^{2} + 15}} \\in (-1; 1)')}
<p>m = intensificador (×1,5 “muito”, ×0,6 “pouco”); n = −0,75 se houver negação até 3 palavras antes; c = 0,5 antes e 1,5 depois de “mas/porém/but”. Rótulo: positivo se s ≥ 0,05, negativo se s ≤ −0,05. Num conjunto de 30 frases rotuladas manualmente (testes automatizados) a acurácia exigida é ≥ 85%; ironia e gírias não são bem tratadas.</p>
<p><b>Aspectos</b> (durabilidade, bateria, aquecimento, defeito elétrico, montagem, assistência técnica, custo-benefício, qualidade, entrega, vendedor, atendimento) são detectados por termos de domínio; cada aspecto recebe o sentimento da frase em que aparece. O <b>alvo</b> da reclamação é entrega, vendedor ou atendimento quando só esses aspectos aparecem; caso contrário, produto.</p>
<p><b>Contagem de reclamações não é taxa de defeito</b>: mede apenas o que foi publicado nas fontes coletadas.</p>
<p><b>YouTube</b>: só a API oficial; métricas exibidas são somas e médias do próprio YouTube, em página separada. Pelas políticas de desenvolvedor do YouTube, esses dados não passam por NLP nem entram no score combinado com outras fontes, e são atualizados ou excluídos em até 30 dias.</p>
<p><b>Cobertura e confiança do score</b>:</p>
${F('\\text{cobertura} = \\sum_{c \\in C} w_{c} \\qquad \\text{confiança} = \\bar{r} \\cdot \\left(0,5 + 0,5 \\min\\left(1; \\frac{n_{f}}{3}\\right)\\right) \\cdot \\left(0,5 + 0,5 \\min\\left(1; \\frac{\\text{meses}}{36}\\right)\\right)')}
<p>r̄ = média da confiabilidade das fontes do produto (A = 1, B = 0,8, C = 0,6); n<sub>f</sub> = número de fontes. Confiança alta ≥ 0,7; média ≥ 0,45. A diversidade de fontes deixou de compor o score para que a falta de uma fonte não reduza a nota — ela aparece na confiança.</p>
<p><b>Comparador</b>: atributos técnicos extraídos por expressões regulares de títulos e resumos (RSS, notícias, Reddit) recebem confiabilidade C e podem misturar modelos diferentes. Marca, modelo e fornecedores só aparecem com fonte estruturada autorizada; caso contrário, “não disponível”.</p>
<p class="muted">Código: <code>backend/gpi/nlp/reviews.py</code>, <code>market/content_intel.py</code>, <code>market/service.py · compare</code></p></div>

<div class="panel" id="m-ml3"><h2>20. Modelos opcionais e tipos de previsão</h2>
<p><b>SARIMA</b> (statsmodels): busca em p, q, P, Q ∈ {0, 1}, d ∈ {0, 1}, D ∈ {0, 1} (D = 1 só com ≥ 3 ciclos), escolhendo o menor AICc; intervalos pela variância do modelo de espaço de estados.</p>
${F('\\phi(B) \\Phi(B^{m}) (1 - B)^{d} (1 - B^{m})^{D} y_{t} = \\theta(B) \\Theta(B^{m}) \\varepsilon_{t}')}
<p><b>LightGBM e XGBoost</b>: mesma formulação em razão ao nível recente da seção 16, com 1 thread. Todos entram como candidatos do AutoML somente se a biblioteca estiver instalada e são escolhidos apenas se vencerem no backtesting.</p>
<p><b>Surto</b> (tendência emergente): média dos últimos 3 meses &gt; média + 2 desvios-padrão dos 24 meses anteriores.</p>
<p><b>Tipos de previsão, nunca convertidos entre si</b>: vendas (planilhas próprias), importação (US$/kg importados), interesse (visualizações), popularidade (menções), indicador (câmbio, varejo), busca (volume aproximado do Google Ads).</p></div>

<div class="panel" id="m-consumo"><h2>21. Inteligência de consumo: produtos, buscas e intenção</h2>
<p><b>Três dimensões separadas</b>: (A) consumo — interesse por produtos específicos (buscas, leitura de artigos, menções); (B) comércio exterior — valor e peso importados por SH4; (C) mercado — preços, avaliações e conteúdo. Volume de buscas, vendas e importações nunca são somados ou comparados diretamente.</p>
<p><b>Catálogo canônico</b> Categoria → Família → Produto → Variante. Cada termo vira um conjunto de conceitos do léxico pt/en/zh; a <b>chave do produto</b> é esse conjunto, independente de idioma e ordem:</p>
${F('\\text{chave}(t) = \\{\\text{núcleo}(t)\\} \\cup Q(t), \\qquad \\text{“wireless charger”} \\equiv \\text{“carregador sem fio”} \\equiv \\text{“无线充电器”} = \\{charger, wireless\\}')}
<p>Atributos numéricos (potência, capacidade, armazenamento, tela) não entram na chave: geram <b>variantes</b> (carregador USB-C 20W ≠ 140W, mesma família). Pipeline: limpeza → idioma (escrita CJK; pistas pt/en) → tokens (máxima correspondência em chinês) → conceitos (correspondência mais longa primeiro) → núcleo (1º em pt/zh; último antes de “for/with” em inglês) → atributos (regex) → chave → variante → categoria. SH4 só é associado quando a classificação do núcleo é inequívoca.</p>
<p><b>Descoberta</b>: um termo observado com produto ainda não catalogado vira candidato; é promovido com ≥ 2 ocorrências, ≥ 2 fontes, ou 1 ocorrência em fonte de busca (Trends, Google Ads). Limites configuráveis evitam consumo excessivo de memória.</p>
<p><b>Intenção</b> (compra, comparação, review, problema técnico, manutenção, informação, entretenimento, notícia): regras em pt/en/zh com prioridade; modelo supervisionado (TF-IDF de caracteres + regressão logística, nomes de produto mascarados) só é usado com ≥ 40 rótulos, ≥ 3 classes e acurácia em validação cruzada ≥ 0,60 — caso contrário, apenas regras. Termo sem sinal = “informação”, nunca demanda de compra. Comerciais: compra, comparação, review.</p>
<p><b>Buscas em alta (Google Trends — Trending Now)</b>: o tráfego vem em faixas (“2.000+”); registra-se o limite inferior e o rótulo da faixa. Só termos com produto identificado e intenção diferente de notícia/entretenimento entram nos rankings. Sem histórico retroativo: a série se forma com as coletas diárias. <b>Google Ads</b>: volumes mensais arredondados pelo Google — tratados como aproximados. <b>China</b>: sem fonte autorizada de buscas (Baidu Index, 巨量算数, Alibaba); Wikipédia em chinês não representa buscas na China.</p>
<p class="muted">Código: <code>backend/gpi/products/lexicon.py, nlp.py, intent.py, catalog.py</code>, <code>connectors/search.py</code></p></div>

<div class="panel" id="m-tendprod"><h2>22. Tendências por produto, rankings, antecedência e scores</h2>
<p><b>Crescimento</b>: com ≥ 15 meses, último trimestre contra o mesmo trimestre do ano anterior (não confunde sazonalidade com tendência); senão, contra o trimestre anterior; buscas em alta: 30 dias contra os 30 anteriores.</p>
${F('g = \\frac{\\bar{y}_{T-2..T}}{\\bar{y}_{T-14..T-12}} - 1 \\qquad a = g_{3m}(T) - g_{3m}(T-3)')}
<p><b>Classes</b>: emergente (primeira observação ≤ 30 dias ou ≤ 3 meses), crescimento consistente (Mann–Kendall p &lt; 0,05 e g &gt; 0; em série sazonal: ≥ 75% das variações anuais positivas e mediana &gt; 5%), crescimento (g &gt; 15%), declínio (queda significativa ou g &lt; −15%), sazonal (Kruskal–Wallis p &lt; 0,05), estável.</p>
<p><b>Pontos de mudança</b>: segmentação binária da média de log(1+y), aceitando a divisão quando a redução do erro quadrático supera a penalidade</p>
${F('\\beta = 2 \\ln(n) \\, \\hat{\\sigma}^{2}, \\qquad \\hat{\\sigma} = 1{,}4826 \\cdot \\text{MAD}(\\Delta y) / \\sqrt{2}')}
<p><b>Anomalias</b>: |z| &gt; 3,5 com z = (y − mediana móvel)/(1,4826·MAD dos resíduos).</p>
<p><b>Antecedência entre mercados (lead-lag)</b>: correlação cruzada das variações padronizadas de log(1+y), defasagens −6…+6; significativa se |ρ| &gt; 1,96/√n; estável se a melhor defasagem se repete (±1) nas duas metades; backtest: Δb(t) previsto por Δa(t−k) contra “sem variação”.</p>
${F('\\rho_{k} = \\text{corr}(\\Delta a_{t}, \\Delta b_{t+k}), \\qquad \\text{ganho} = 1 - \\frac{\\sum |\\Delta b_{t} - \\hat{\\alpha} - \\hat{\\beta} \\Delta a_{t-k}|}{\\sum |\\Delta b_{t}|}')}
<p>É um sinal exploratório: correlação não é causalidade, e não se afirma que uma tendência chegará ao Brasil.</p>
<p><b>Rankings</b> declaram o que medem. “Mais pesquisados” usa somente volume de buscas; sem essa fonte, fica vazio com a explicação.</p>
<p><b>Scores</b> (0–100, separados): <b>Opportunity</b> = média ponderada dos componentes disponíveis (crescimento Brasil 0,22; internacional 0,14; persistência 0,14; intenção de compra 0,16; concorrência baixa 0,10; estabilidade sazonal 0,06; baixa volatilidade 0,08; qualidade dos dados 0,10), sem penalizar fontes ausentes; <b>Evidence Coverage</b> = 50·(peso disponível) + 50·min(1, fontes/4); <b>Forecast Confidence</b> = qualidade no backtesting × fator de histórico (0 sem previsão validada); <b>Import Readiness</b> = fração de verificações concluídas (NCM fundamentado, importações monitoradas, volume de buscas, previsão validada, intenção de compra, preços). Margem, rentabilidade e quantidade de compra não são estimadas.</p>
<p class="muted">Código: <code>backend/gpi/products/trends.py</code></p></div>

<div class="panel" id="m-v05"><h2>23. Versão 0.5: modelo global, intervalos conformais, mudanças e viabilidade</h2>
<p><b>Modelo global multi-série</b> (mesma ideia do MLForecast): um modelo por métrica, treinado com todas as séries elegíveis. Alvo e defasagens em razão ao nível recente:</p>
${F('\\tilde{y}_{i,t} = \\frac{y_{i,t}}{\\bar{y}_{i,t-3..t-1}}, \\qquad \\hat{y}_{i,t} = \\bar{y}_{i,t-3..t-1} \\cdot f(\\tilde{y}_{i,t-1}, \\tilde{y}_{i,t-2}, \\tilde{y}_{i,t-3}, \\tilde{y}_{i,t-6}, \\tilde{y}_{i,t-12}, m_t, \\text{família}, \\text{categoria}, \\text{país}, \\text{fonte})')}
<p>f = HistGradientBoosting, LightGBM, XGBoost ou CatBoost. Comparação com o modelo local nas mesmas origens de backtesting; em cada série vale o de menor WAPE.</p>
<p><b>Intervalos conformais</b>: erros relativos e<sub>h</sub> = (y − ŷ)/ŷ das origens antigas; quantil com correção de amostra finita; cobertura medida na origem mais recente.</p>
${F('q_{h}^{(1-\\alpha)} = \\text{Quantil}_{⌈(n+1)(1-\\alpha)⌉/n} \\left( |e_{h}| \\right), \\qquad \\left[\\hat{y}/(1+q), \\quad \\hat{y}(1+q)\\right]')}
<p><b>Mudanças de comportamento</b> — ADWIN: corta a janela quando |μ₀ − μ₁| &gt; ε; Page-Hinkley: alarme quando a soma acumulada dos desvios passa de λ.</p>
${F('\\varepsilon_{cut} = \\sqrt{\\frac{1}{2m} \\ln\\frac{4n}{\\delta}}, \\quad m = 1 / (1/n_{0} + 1/n_{1}) \\qquad m_{T} = \\sum_{t \\le T} (x_{t} - \\bar{x}_{t} - \\delta), \\quad m_{T} - \\min m > \\lambda')}
<p><b>Reconciliação hierárquica</b> (só volumes aditivos): ỹ = S·P·ŷ, com P de Bottom-Up, Top-Down (proporções históricas), MinT-OLS P = (SᵀS)⁻¹Sᵀ ou MinT-WLS P = (SᵀW⁻¹S)⁻¹SᵀW⁻¹, W = diag(S·1).</p>
<p><b>Discovery 2.0</b>: correção de grafia por similaridade ≥ 88 (palavras ≥ 5 letras); alias por similaridade ≥ 92 só com o mesmo núcleo e nenhum atributo numérico divergente.</p>
<p><b>Early Trend Detection</b>: persistência = fração de variações positivas (ano contra ano em série sazonal); base mínima por métrica para entrar em rankings de crescimento; possível saturação = crescimento &gt; 0, aceleração &lt; −10 p.p. e média recente ≥ 90% do máximo; confiança da classificação = 0,4·min(1, n/36) + 0,3·[p &lt; 0,05] + 0,3·cobertura.</p>
<p><b>Viabilidade de importação</b>: custo nacionalizado com ICMS “por dentro”; Monte Carlo com distribuições triangulares (mín, base, máx) informadas pelo usuário; pedido ótimo:</p>
${F('Q^{*} = \\arg\\max_{Q \\ge MOQ, Q \\cdot c \\le B} \; \\frac{1}{N}\\sum_{k} \\left[ \\min(Q, D_{k}) \\, p_{k} - Q \\, c_{k} \\right]')}
<p class="muted">Código: <code>backend/gpi/forecasting/advanced.py</code>, <code>products/discovery.py</code>, <code>market/viability.py</code>, <code>market/reviews2.py</code></p></div>
<div class="panel" id="m-v06"><h2>24. Versão 0.6: redes sociais, oportunidades 3.0 e relatórios</h2>
<p><b>Normalização por plataforma.</b> Para cada plataforma p e métrica m, o crescimento g de cada produto vira o seu percentil entre os produtos daquela mesma plataforma e métrica (empates recebem a média). Curtidas, visualizações e publicações nunca são somadas entre plataformas.</p>
${F('\\pi_{i}^{(p,m)} = \\frac{\\text{posto}(g_{i}^{(p,m)})}{N^{(p,m)} - 1}')}
<p><b>Social Trend Score</b> (0–100, exploratório): média ponderada dos componentes disponíveis, renormalizada pela cobertura — crescimento (média, entre plataformas, do maior percentil de cada uma) 35%, persistência 20%, engajamento relativo (percentil do nível) 15%, diversidade de plataformas 15%, intenção comercial 15%.</p>
${F('STS_{i} = 100 \\cdot \\frac{\\sum_{k \\in K_{i}} w_{k} c_{i,k}}{\\sum_{k \\in K_{i}} w_{k}}')}
<p><b>Viral Product Radar</b>: emergente = primeira observação recente; viralização recente = mais que dobrou em 7 dias ou anomalia no último período, com persistência &lt; 50%; sustentado = crescimento &gt; 15% com persistência ≥ 50%; saturação = desaceleração perto do máximo; declínio = queda &gt; 15%; demais = estável. Crescimento em uma única plataforma é sinalizado.</p>
<p><b>Search vs. Social</b>: Search Growth, Social Growth e Marketplace Signals ficam separados. A consistência compara só a direção (s ∈ {−1, 0, +1}, zona neutra de ±5%) entre os tipos de fonte; com ≥ 8 meses comuns, também a correlação de Spearman.</p>
${F('CSC_{i} = \\frac{2}{k(k-1)} \\sum_{a<b} s_{a} s_{b}')}
<p><b>Opportunity Engine 3.0</b>: busca 25%, social 10%, marketplace 15%, persistência 15%, (100 − concorrência) 10%, (100 − risco de qualidade) 10%, previsão 5%, prontidão 10%; dimensões sem dados não entram. Prioridade "Evidência insuficiente" se cobertura &lt; 40 ou menos de duas dimensões de demanda; "Alta" exige índice ≥ 65 e dois tipos de fonte independentes em alta.</p>
<p><b>Sinais sociais no ML</b>: mesmo modelo global, com e sem defasagens sociais (t−1, t−2); origem móvel, 1 passo à frente. Adoção só se o WAPE cair ≥ 2% no total e em ≥ 75% das origens.</p>
<p><b>Relatórios</b>: cada tabela declara a natureza do dado (observado, estimado, projeção, derivado); recortes de período recalculam os indicadores mensais só com os meses do recorte; um snapshot dos dados acompanha cada arquivo para reprodução.</p>
<p class="muted">Código: <code>backend/gpi/social/</code>, <code>products/opportunity3.py</code>, <code>forecasting/social_ablation.py</code>, <code>reports/</code></p></div>
</div>`;
};
