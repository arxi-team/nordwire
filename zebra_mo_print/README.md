# Impressão de etiquetas Zebra ao confirmar MO (coffeepilot / SK Coffee)

## Arquitetura
- **Servidor Odoo** (`odoo_module/`, nome tecnico `zebra_mo_print`): modulo que, ao confirmar
  uma Ordem de Fabrico, liga por SSH a um PC Windows e manda imprimir a etiqueta.
  ATUALMENTE instalado em:
  `/var/odoo/coffeepilot.flybyodoo.pt/extra-addons/nordwire.git-6ad1e62b435d3/zebra_mo_print`
  (dentro do repositorio do nordwire - ver nota abaixo).
- **PC Windows** (`windows/print_zpl.ps1`): script que recebe o nome da MO/produto e manda o ZPL
  (desenho completo da etiqueta) diretamente para a impressora Zebra ZD421 ligada por USB.
  E aqui que vive todo o desenho da etiqueta (logo, QR codes, icones, textos, tamanhos).

**NOTA IMPORTANTE:** o modulo esta atualmente dentro da pasta do repositorio git do nordwire,
o que pode causar conflitos se esse repo for atualizado por outra via. Considera mover para uma
pasta/repo proprio (ex: `custom-addons/zebra_mo_print`) assim que possivel.

A impressora Zebra nao funciona bem por USB ligada diretamente ao Linux (testado
exaustivamente - erro de protocolo USB ao nivel do kernel, provavelmente falha de hardware na
interface USB da impressora). Por isso usa-se um PC Windows como ponte.

## Instalar modulo no Odoo (se o servidor mudar ou mover de pasta)
```bash
sudo cp -r odoo_module /var/odoo/<db>/custom-addons/zebra_mo_print
sudo chown -R odoo:odoo /var/odoo/<db>/custom-addons/zebra_mo_print
# garantir que custom-addons esta no addons_path do odoo.conf
sudo -u odoo bash -c 'cd /var/odoo/<db> && venv/bin/python3 src/odoo-bin -c odoo.conf -d <db> -i zebra_mo_print --stop-after-init'
sudo systemctl restart <nome-do-servico-odoo>
```
No `models/mrp_production.py`, atualizar `SSH_KEY` e `WIN_HOST` se o caminho da chave ou o
IP/utilizador do Windows mudarem.

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
4. **Copiar os ficheiros deste pacote para `C:\`**:
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
  `icon_envelope.zpl.txt`). O icone do telefone usa a fonte Noto Sans Symbols2 (glifo U+260E).
Precisa de Python 3 + Pillow (`pip install Pillow`).

## Tamanho da etiqueta atual
100mm x 125mm = 800x1000 dots a 203dpi (`^PW800 ^LL1000` no ZPL).

## Dados de contacto usados na etiqueta
Telefone, email e tagline estao escritos diretamente no `print_zpl.ps1` (nao vêm do Odoo).
Atualizar ali se mudarem.
