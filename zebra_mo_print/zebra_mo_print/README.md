# Impressão de etiquetas Zebra ao confirmar MO (coffeepilot / SK Coffee)

## Arquitetura
- **Servidor Odoo** (`odoo_module/zebra_mo_print`): módulo que, ao confirmar uma Ordem de Fabrico,
  liga por SSH a um PC Windows e manda imprimir a etiqueta.
- **PC Windows** (`windows/print_zpl.ps1`): script que recebe o nome da MO/produto e manda o ZPL
  (desenho completo da etiqueta) diretamente para a impressora Zebra ZD421 ligada por USB.
  É aqui que vive todo o desenho da etiqueta (logo, QR codes, textos, tamanhos).

A impressora Zebra **não funciona bem por USB ligada diretamente ao Linux** (testado
exaustivamente — erro de protocolo USB ao nível do kernel, provavelmente falha de hardware na
interface USB da impressora). Por isso usa-se um PC Windows como ponte: o Windows comunica bem
com ela via USB (driver ZDesigner), e o Odoo fala com o Windows por SSH.

## Instalar módulo no Odoo (se o servidor mudar)
```bash
sudo cp -r odoo_module/zebra_mo_print /var/odoo/<db>/custom-addons/
sudo chown -R odoo:odoo /var/odoo/<db>/custom-addons/zebra_mo_print
# garantir que custom-addons está no addons_path do odoo.conf
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
Copiar a chave pública gerada para o Windows (ver abaixo).

## Configurar um PC Windows novo (se o atual avariar)
1. **Instalar o driver da Zebra ZD421** (driver "ZDesigner ZD421-203dpi ZPL") — vem com a
   instalação normal da impressora ou via Zebra Setup Utilities (zebra.com/support).
2. **Ativar o servidor SSH do Windows** (PowerShell como Administrador):
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd
   Set-Service -Name sshd -StartupType Automatic
   New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
   ```
3. **Autorizar a chave pública do servidor Odoo** (gerada no passo anterior):
   ```powershell
   Add-Content -Path "$env:ProgramData\ssh\administrators_authorized_keys" -Value "<chave publica aqui>"
   icacls "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r
   icacls "$env:ProgramData\ssh\administrators_authorized_keys" /grant "*S-1-5-32-544:F" "*S-1-5-18:F"
   Restart-Service sshd
   ```
   (os SIDs `S-1-5-32-544` e `S-1-5-18` são universais — Administradores e SYSTEM, independentes
   do idioma do Windows)
4. **Copiar os ficheiros deste pacote para `C:\`**:
   - `windows/print_zpl.ps1` → `C:\print_zpl.ps1`
   - `windows/logo.zpl.txt` → `C:\logo.zpl.txt`
5. **Atualizar `WIN_HOST` no módulo Odoo** (`models/mrp_production.py`) se o IP/utilizador do
   Windows novo for diferente (atualmente via Tailscale).
6. **Testar manualmente** (no servidor Odoo, como utilizador `odoo`):
   ```bash
   sudo -u odoo ssh -i /var/odoo/<db>/.ssh/id_zebra_win -o IdentitiesOnly=yes <user>@<ip-windows> \
     'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\print_zpl.ps1 -MoName "TESTE" -QrData "TESTE" -ProductName "Produto Teste"'
   ```
   Deve responder `PRINTED` e sair uma etiqueta.

## Regenerar o gráfico do logo (se precisares de o alterar)
`windows/img_to_zpl.py` converte `windows/Logo SK.png` num campo gráfico ZPL (`logo.zpl.txt`).
Precisa de Python 3 + Pillow (`pip install Pillow`). Ajustar `target_width` no início do ficheiro
para mudar o tamanho do logo na etiqueta.

## Tamanho da etiqueta atual
100mm x 125mm = 800x1000 dots a 203dpi (`^PW800 ^LL1000` no ZPL).
