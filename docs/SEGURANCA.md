# Segurança e distribuição do GPI.exe (v0.6)

## O que o pacote faz — e não faz
* Abre um servidor **somente em 127.0.0.1** (porta 8765 ou a próxima livre) e o navegador padrão.
* Executa como o usuário (**asInvoker**): nunca pede privilégio administrativo. Não cria serviço do Windows, tarefa
  agendada, inicialização automática, regra de firewall ou exclusão de antivírus.
* Dados em `%LOCALAPPDATA%\GPI` (pasta gravável do usuário). Credenciais protegidas com DPAPI (Windows).
* Conexões externas: apenas as APIs das fontes públicas e das integrações que o usuário conectou (lista completa no
  relatório `relatorios/seguranca.md`, gerado a cada build). Cada fonte consultada fica registrada em *Saúde das Fontes*.
* Empacotamento PyInstaller **one-folder** (sem extração em pasta temporária), **sem UPX, sem ofuscação, sem técnicas
  de evasão**. Módulos de teste e bibliotecas não usadas são excluídos; o relatório confirma.

## Redes sociais, privacidade e relatórios (v0.6)
* Somente APIs oficiais com autorização do usuário (OAuth nas páginas da TikTok e da Meta); o GPI nunca pede senha de
  rede social. Não há raspagem, endpoints privados nem contorno de autenticação. A TikTok Research API não é usada.
* Só **agregados** são guardados (posições, contagens, medianas de engajamento) e o link público de referência. Textos
  de publicações e nomes de usuários não são armazenados (o texto de páginas do Facebook é lido para identificar o produto
  e descartado). Prazos de retenção por fonte (padrão 90 dias para TikTok e Meta, 36 meses para estatísticas do YouTube),
  configuráveis; os dados vencidos são apagados a cada análise.
* Relatórios exportam apenas agregados e links permitidos; tokens e credenciais nunca entram em relatórios, snapshots,
  logs ou arquivos exportados (filtro adicional remove qualquer campo com nome de credencial).
* Relatórios são salvos só neste computador; o relatório semanal automático é opcional e nada é enviado para fora.

## Verificações automáticas em cada build (GitHub Actions)
1. Testes do executável numa cópia sem Python no PATH (inicialização, servidor, interface, modelos — incluindo os
   modelos globais LightGBM/XGBoost/CatBoost —, persistência, encerramento, integridade, porta liberada).
2. **Microsoft Defender** (`MpCmdRun -Scan -ScanType 3 -File dist/GPI`) com definições atualizadas no runner. Se houver
   detecção, o build falha e o pacote não é publicado; a causa deve ser investigada e, se for falso positivo, enviada à
   Microsoft pelo canal oficial (https://www.microsoft.com/wdsi/filesubmission). O GPI nunca pede para desativar o antivírus.
3. **Relatório de segurança**: arquivos e binários nativos, ausência de credenciais embutidas, nível de execução do
   manifesto, status da assinatura, endereços externos usados pelo código.
4. **SHA-256** do `GPI.exe` e do `GPI-Windows-Portable-v0.5.zip` em `SHA256SUMS.txt`, publicado junto ao artefato; o ZIP
   é extraído novamente e conferido (hash do executável e `GPI.exe --check`).

Para conferir o download no Windows: `Get-FileHash .\GPI-Windows-Portable-v0.5.zip -Algorithm SHA256` e comparar com
`SHA256SUMS.txt`.

## Identidade e assinatura digital — situação atual: **NÃO ASSINADO**
* Metadados do executável: *Global Product Intelligence*, versão 0.5.0, descrição "Global Product Intelligence — Market
  Research and Demand Forecasting", ícone próprio. **Sem nome de editor (CompanyName)**: só será preenchido com uma
  identidade legal comprovada e autorizada.
* **Microsoft Artifact Signing** (antigo Trusted Signing): em 2025–2026 a inscrição de organizações está limitada a
  empresas dos EUA e do Canadá com 3 anos de histórico verificável; a de pessoas físicas está pausada. **Uma empresa
  brasileira não pode se inscrever hoje** (verificar novamente: https://learn.microsoft.com/azure/artifact-signing/).
* **Certificado Authenticode** de autoridade certificadora pública (OV/EV): é o caminho disponível para o Brasil; exige
  validação da empresa e hoje armazenamento da chave em hardware (token/HSM ou serviço de nuvem da CA).
* **Microsoft Store** (MSIX): a loja assina o pacote; exige conta de desenvolvedor e empacotamento MSIX.
* **Assinatura corporativa** com certificado interno da empresa: válida dentro da empresa, se a TI distribuir a raiz.
* Certificado autoassinado **não** substitui confiança pública e não é usado.
* Assinatura não garante ausência de aviso do SmartScreen: a reputação também se forma com o tempo e o volume de downloads.

O workflow já está preparado: ao cadastrar os segredos `SIGN_ENDPOINT`, `SIGN_ACCOUNT`, `SIGN_PROFILE`, `AZURE_TENANT_ID`,
`AZURE_CLIENT_ID` e `AZURE_CLIENT_SECRET` no repositório (Settings → Secrets), a etapa de assinatura passa a rodar antes do
manifesto de integridade. Nenhuma credencial fica no código.
