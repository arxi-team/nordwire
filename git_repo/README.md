# Impressão de etiquetas Zebra ao confirmar MO (coffeepilot / SK Coffee)

## Estrutura deste repositorio (propositadamente "plana" para git pull)
```
zebra_mo_print/   <- modulo Odoo, pronto a usar tal como esta (manifest no topo)
windows/          <- script de impressao + geradores de logo/icones (PC Windows ponte)
README.md
```
Esta pasta foi desenhada para que `zebra_mo_print/` possa ser usada DIRETAMENTE como
addons_path no Odoo, sem desembrulhar nada. Clona este repositorio para dentro de
`extra-addons/` e aponta o `addons_path` para a pasta do repositorio (nao para dentro do
`zebra_mo_print/`) - o Odoo encontra o modulo automaticamente la dentro.

## Arquitetura
- **Servidor Odoo** (`zebra_mo_print/`): ao confirmar uma Ordem de Fabrico, liga por SSH a um
  PC Windows e manda imprimir a etiqueta. Le sempre da MO real: `self.name` (referencia) e
  `self.product_id.name` (produto) - nunca valores fixos.
- **PC Windows** (`windows/print_zpl.ps1`): recebe o nome da MO/produto e manda o ZPL (desenho
  completo da etiqueta) direto para a impressora Zebra ZD421 por USB. E aqui que vive o
  desenho da etiqueta (logo, QR codes, icones, textos, tamanhos).

A impressora Zebra nao funciona bem por USB ligada diretamente ao Linux (testado
exaustivamente - erro de protocolo USB ao nivel do kernel). Por isso usa-se um PC Windows
como ponte.

## Instalar/atualizar no servidor via git pull
Primeira vez (clonar):
```bash
cd /var/odoo/<db>/extra-addons
sudo -u odoo git clone <url-do-teu-repo> zebra-mo-print-repo
```
Adicionar ao `addons_path` do `odoo.conf` a pasta do repositorio (nao a do modulo):
```
addons_path = ..., /var/odoo/<db>/extra-addons/zebra-mo-print-repo, ...
```
Instalar o modulo (primeira vez) e reiniciar:
```bash
sudo -u odoo bash -c 'cd /var/odoo/<db> && venv/bin/python3 src/odoo-bin -c odoo.conf -d <db> -i zebra_mo_print --stop-after-init'
sudo systemctl restart <nome-do-servico-odoo>
```

**Atualizacoes seguintes** (depois de alterares e dar `git push` daqui, ex: do teu PC):
```bash
cd /var/odoo/<db>/extra-addons/zebra-mo-print-repo
sudo -u odoo git pull
sudo systemctl restart <nome-do-servico-odoo>
```
Pronto - nunca mais e preciso copiar/mover ficheiros a mao no servidor.

No `zebra_mo_print/models/mrp_production.py`, atualizar `SSH_KEY` e `WIN_HOST` se o caminho da
chave ou o IP/utilizador do Windows mudarem.

### Chave SSH do servidor para o Windows
No servidor Odoo, como utilizador `odoo`:
```bash
sudo -u odoo ssh-keygen -t ed25519 -f /var/odoo/<db>/.ssh/id_zebra_win -N ""
```
Copiar a chave publica gerada para o Windows (ver abaixo).

## Configurar um PC Windows novo (se o atual avariar)
1. **Instalar o driver da Zebra ZD421** ("ZDesigner ZD421-203dpi ZPL") - Zebra Setup Utilities
   (zebra.com/support).
2. **Ativar o servidor SSH do Windows** (PowerShell como Administrador):
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd
   Set-Service -Name sshd -StartupType Automatic
   New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
   ```
3. **Autorizar a chave publica do servidor Odoo**:
   ```powershell
   Add-Content -Path "$env:ProgramData\ssh\administrators_authorized_keys" -Value "<chave publica aqui>"
   icacls "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r
   icacls "$env:ProgramData\ssh\administrators_authorized_keys" /grant "*S-1-5-32-544:F" "*S-1-5-18:F"
   Restart-Service sshd
   ```
   (SIDs universais, independentes do idioma do Windows)
4. **Copiar os ficheiros deste repositorio para `C:\`** (ou clonar o repo la tambem):
   - `windows/print_zpl.ps1` -> `C:\print_zpl.ps1`
   - `windows/logo.zpl.txt` -> `C:\logo.zpl.txt`
   - `windows/icon_phone.zpl.txt` -> `C:\icon_phone.zpl.txt`
   - `windows/icon_envelope.zpl.txt` -> `C:\icon_envelope.zpl.txt`
5. **Atualizar `WIN_HOST`** no modulo Odoo se o IP/utilizador do Windows novo mudar (atualmente
   via Tailscale).
6. **Testar manualmente** (servidor Odoo, utilizador `odoo`):
   ```bash
   sudo -u odoo ssh -i /var/odoo/<db>/.ssh/id_zebra_win -o IdentitiesOnly=yes <user>@<ip-windows> \
     'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\print_zpl.ps1 -MoName "TESTE" -QrData "TESTE" -ProductName "Produto Teste"'
   ```
   Deve responder `PRINTED` e sair uma etiqueta.

## Regenerar os graficos (logo / icones)
- `windows/img_to_zpl.py`: converte `windows/Logo SK.png` num campo grafico ZPL (`logo.zpl.txt`).
  Ajustar `target_width` para mudar o tamanho do logo.
- `windows/make_icons.py`: gera os icones de telefone e envelope (`icon_phone.zpl.txt`,
  `icon_envelope.zpl.txt`).
Precisa de Python 3 + Pillow (`pip install Pillow`).

## Tamanho da etiqueta atual
100mm x 125mm = 800x1000 dots a 203dpi (`^PW800 ^LL1000` no ZPL).

## Dados de contacto usados na etiqueta
Telefone, email e tagline estao escritos diretamente no `print_zpl.ps1` (nao vêm do Odoo).
Atualizar ali se mudarem.

## Dados que VÊM sempre do Odoo (nunca fixos)
`zebra_mo_print/models/mrp_production.py` le, de cada MO confirmada: `self.name` (referencia
da MO, ex. `MO/00123`) e `self.product_id.name` (nome do produto a fabricar) - e manda os dois
para o `print_zpl.ps1` via `-MoName`/`-QrData`/`-ProductName`. Nunca sao valores fixos.
