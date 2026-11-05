# Atualizar para a v0.9 preservando o SQLite

1. **Feche o GPI** (botão Encerrar ou ícone da bandeja). Não atualize com ele aberto.
2. **Copie a pasta de dados** para um lugar seguro (backup manual). Por padrão ela fica em `%LOCALAPPDATA%\GPI`
   (cole esse endereço no Explorador de Arquivos); no modo pen-drive (arquivo `portable.flag` ao lado do `GPI.exe`)
   é a pasta `dados` ao lado do executável. Ela contém `gpi.sqlite`, as credenciais (protegidas por DPAPI) e os
   relatórios. A pasta exata aparece em Fontes e Sistema → Diagnóstico.
3. Extraia `GPI-Windows-Portable-v0.9.zip` numa pasta nova (no modo pen-drive, copie para ela a pasta `dados` e o
   `portable.flag`). A pasta de dados em `%LOCALAPPDATA%\GPI` é reaproveitada automaticamente.
4. Abra o `GPI.exe`. Na primeira sincronização e análise (que começam ao abrir) a v0.9:
   * cria tabelas novas (`product_taxonomy`, `association_review`, `alert_state`); nenhuma tabela ou registro é apagado.
     A única alteração em dados existentes é o produto associado a cada vídeo (próximo item), com o valor anterior guardado;
   * reavalia as associações de vídeos do YouTube; a associação anterior fica registrada em cada vídeo
     (`produto_anterior`) e as duvidosas vão para **Revisão de associações**;
   * recalcula estágios e alertas.
5. As credenciais continuam valendo (DPAPI é por usuário do Windows: use a mesma conta). O Login básico da Meta
   não precisa ser refeito.

**Voltar à versão anterior:** feche o GPI e use a pasta antiga com a cópia de `dados` do passo 2. As tabelas novas
não atrapalham versões anteriores.

Não é preciso Python, Node.js, administrador nem instalação.
