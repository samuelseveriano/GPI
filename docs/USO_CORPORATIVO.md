# GPI v0.7 — instruções para uso corporativo (TI e usuário)

## Instalação (sem administrador)
1. Baixe `GPI-Windows-Portable-v0.7.zip` do artefato do GitHub Actions e confira o SHA-256 publicado em `SHA256SUMS.txt`
   (`Get-FileHash .\GPI-Windows-Portable-v0.7.zip`).
2. Extraia em uma pasta do usuário (ex.: `Documentos\GPI`) e execute `GPI.exe`. Dados ficam em `%LOCALAPPDATA%\GPI`
   (ou ao lado do exe com `portable.flag`). Nada é instalado no sistema; nenhum serviço do Windows é criado.
3. O executável não é assinado por padrão: o SmartScreen pode avisar. Não desative o Defender nem o SmartScreen; peça à TI
   para validar o hash e, se a política exigir, assinar internamente ou liberar pelo procedimento oficial.

## IA local (opcional)
1. Em computador autorizado, baixe `GPI-Local-AI-Model-Pack-v0.7.zip` e confira o SHA-256 (`SHA256SUMS-IA.txt`).
2. Transfira pelo procedimento aprovado pela TI e extraia a pasta `ia` ao lado do `GPI.exe` (ou em `%LOCALAPPDATA%\GPI\ia`).
3. GPI → Conformidade de Importação → IA Local: o GPI confere licença e SHA-256 de cada arquivo; escolha o modo e os limites
   (RAM padrão 2048 MB, threads = metade dos núcleos, contexto 4096). Sem o pacote, ou se a política bloquear
   `llama-server.exe`, o GPI continua no Modo Essencial e mostra a mensagem.
4. O processo do modelo escuta só em 127.0.0.1 e não acessa a internet; é encerrado junto com o GPI.

## Endereços usados (liberar no proxy, se desejado)
| Uso | Endereço |
|---|---|
| Tabela NCM oficial (botão "Baixar tabela oficial") | portalunico.siscomex.gov.br |
| Dados abertos de homologações Anatel | www.anatel.gov.br |
| Verificação das fontes da base regulatória | gov.br, planalto.gov.br, anatel.gov.br, inmetro.gov.br, siscomex.gov.br |
| Mercado Livre (OAuth/API) | auth.mercadolivre.com.br, api.mercadolibre.com, samuelseveriano.github.io |

Sem acesso a esses endereços, a TI pode entregar arquivos: tabela NCM (JSON oficial) em Conformidade → NCM → "Carregar
arquivo da TI"; ZIP de homologações em Homologações → "Carregar ZIP da TI"; pacote da base regulatória (com SHA-256
publicado) em Base regulatória → "Importar pacote offline".

## Dados e sigilo
Análises, anexos de fornecedores, relatórios e credenciais ficam só no computador. O diagnóstico exportado não contém
credenciais. Não envie bancos, relatórios ou documentos de fornecedores para o repositório público (o `.gitignore` e o
gancho de commit bloqueiam os tipos conhecidos).

## Uso responsável da Conformidade de Importação
A análise é triagem: confirme sempre nos canais oficiais (Anatel, Inmetro, Classif, Simulador de Tratamento
Administrativo) e com despachante/profissional de conformidade antes de importar.
