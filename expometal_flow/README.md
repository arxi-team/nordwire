# expometal_flow — painel da linha de produção dentro do Odoo

O mesmo ecrã que o servidor do stand serve em `/flow/v5/`, servido pelo próprio Odoo 19 (só utilizadores com sessão iniciada):

| Endereço | Painel |
|---|---|
| `/flow/v5/?clean` | Linha de produção (Ordens de Trabalho → Torra → Embalamento → Entregue) |

Acrescentar `?clean` para o modo de ecrã de stand. Também há um menu em **Fabrico → Painel EXPOMETAL → Linha de produção**.
No Raspberry Pi o ecrã corre o perfil leve sozinho (máquinas em sequência de imagens, sem animações contínuas).

Os dados vêm só deste Odoo, em leitura, de 5 em 5 s (`/flow/v5/data`): ordens de fabrico por iniciar, ordens de
trabalho nos centros de torra e de embalamento (sessões de trabalho e paragens, operador com nome próprio + inicial,
ordens por fechar), entregas prontas que vêm de uma produção (com a MO de cada uma). Quando uma entrega é validada, o ecrã
mostra o resumo de produção dessa encomenda (`/flow/v5/summary`): tempos por centro, esperas e custo. Nada é
escrito no Odoo e não aparecem nomes de clientes.

## Instalação
1. Copiar a pasta `expometal_flow` (do zip `dist/expometal_flow.zip`) para a pasta de addons personalizados.
2. Atualizar a lista de aplicações e instalar **EXPOMETAL · Painel da linha de produção**. Depende de `mrp`, `sale_mrp`, `crm`.

## Configuração (opcional)
Nomes dos centros de trabalho, em *Definições → Técnico → Parâmetros de sistema*:
- `expometal_flow.wc_roast` (por omissão `Torragem`)
- `expometal_flow.wc_pack` (por omissão `Embalagem`)

## Gerar de novo
Os ficheiros de `static/web/` são gerados a partir de `app/web` com `python3 tools/odoo-addon/build.py`.
A lógica dos dados (`controllers/main.py`) acompanha `app/server/odoo/flow.js`: uma mudança num deve ir para o outro.
