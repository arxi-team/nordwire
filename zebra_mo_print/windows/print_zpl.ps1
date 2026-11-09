param(
    [Parameter(Mandatory=$true)][string]$MoName,
    [Parameter(Mandatory=$false)][string]$QrData,
    [Parameter(Mandatory=$false)][string]$ProductName
)

$PrinterName = "ZDesigner ZD421-203dpi ZPL"
if (-not $QrData) { $QrData = $MoName }

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class RawPrinterHelper2
{
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public class DOCINFOA
    {
        [MarshalAs(UnmanagedType.LPStr)] public string pDocName;
        [MarshalAs(UnmanagedType.LPStr)] public string pOutputFile;
        [MarshalAs(UnmanagedType.LPStr)] public string pDataType;
    }
    [DllImport("winspool.Drv", EntryPoint="OpenPrinterA", SetLastError=true, CharSet=CharSet.Ansi, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool OpenPrinter(string src, out IntPtr hPrinter, IntPtr pd);
    [DllImport("winspool.Drv", EntryPoint="ClosePrinter", SetLastError=true, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool ClosePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint="StartDocPrinterA", SetLastError=true, CharSet=CharSet.Ansi, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool StartDocPrinter(IntPtr hPrinter, int level, [In, MarshalAs(UnmanagedType.LPStruct)] DOCINFOA di);
    [DllImport("winspool.Drv", EntryPoint="EndDocPrinter", SetLastError=true, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool EndDocPrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint="StartPagePrinter", SetLastError=true, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool StartPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint="EndPagePrinter", SetLastError=true, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool EndPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint="WritePrinter", SetLastError=true, ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern bool WritePrinter(IntPtr hPrinter, byte[] pBytes, int dwCount, out int dwWritten);

    public static bool SendBytesToPrinter(string printerName, byte[] bytes)
    {
        IntPtr hPrinter;
        DOCINFOA di = new DOCINFOA();
        di.pDocName = "ZPL Label";
        di.pDataType = "RAW";
        if (!OpenPrinter(printerName, out hPrinter, IntPtr.Zero)) return false;
        try
        {
            if (!StartDocPrinter(hPrinter, 1, di)) return false;
            if (!StartPagePrinter(hPrinter)) return false;
            int written;
            bool ok = WritePrinter(hPrinter, bytes, bytes.Length, out written);
            EndPagePrinter(hPrinter);
            EndDocPrinter(hPrinter);
            return ok;
        }
        finally { ClosePrinter(hPrinter); }
    }
}
"@

$moSafe = $MoName -replace '[\^~]', ''
$qrSafe = $QrData -replace '[\^~]', ''
$prodLine = ""
if ($ProductName) {
    $prodSafe = $ProductName -replace '[\^~]', ''
    $prodLine = "^FO40,860^FB480,2,6,L,0^A0N,26,26^FD$prodSafe^FS`n"
}
$logoField = Get-Content "C:\logo.zpl.txt" -Raw
$logoBlock = "^FO160,10$logoField^FS`n"
$ofertaLabel = "^FO605,10^GB185,58,58,B,8^FS`n^FO630,25^FR^A0N,36,36^FDOFERTA^FS`n"

# QR do site (mais pequeno) + bloco de contacto ao lado
$siteQr = "^FO40,548^BQN,2,6`n^FDMA,https://www.skcoffee.com^FS`n"
$eAcute = [char]0x00E9
$tagline = "Caf" + $eAcute + " para empresas"
$phoneIconField = Get-Content "C:\icon_phone.zpl.txt" -Raw
$envIconField = Get-Content "C:\icon_envelope.zpl.txt" -Raw
$phoneIcon = "^FO230,541$phoneIconField^FS`n"
$envIcon = "^FO230,594$envIconField^FS`n"
$contactBlock = "$phoneIcon^FO288,562^A0N,26,18^FD+351 244 237 810^FS`n$envIcon^FO288,602^A0N,24,24^FDcomercial@skcoffee.com^FS`n^FO230,648^A0N,32,32^FD$tagline^FS`n"

# Traço separador (nao chega as extremidades)
$separator = "^FO60,725^GB680,3,3^FS`n"

# Linha da MO: tamanho de letra ajusta-se ao comprimento do texto, para nunca
# ultrapassar a caixa nem invadir o QR code a direita (largura util ~445 dots)
$moFontSize = [Math]::Min(80, [Math]::Max(34, [int](445 / (0.62 * [Math]::Max(1,$moSafe.Length)))))
$moYOffset = 768 + [int]((80 - $moFontSize) / 2)
$moRow = "^FO40,750^GB470,100,100,B,10^FS`n^FO65,$moYOffset^FR^A0N,$moFontSize,$moFontSize^FD$moSafe^FS`n^FO535,750^BQN,2,10`n^FDMA,$qrSafe^FS`n"

# Links por baixo do produto, um por baixo do outro
$linksLine = "^FO40,915^A0N,40,40^FDnordwire.pt^FS`n^FO40,958^A0N,40,40^FDarxi.pt^FS`n"

# Label real: 100x125mm a 203dpi = 800x1000 dots
$zpl = "^XA`n^PW800`n^LL1000`n^CI28`n$logoBlock$ofertaLabel$siteQr$contactBlock$separator$moRow$prodLine$linksLine^XZ`n"

$bytes = [System.Text.Encoding]::UTF8.GetBytes($zpl)
$ok = [RawPrinterHelper2]::SendBytesToPrinter($PrinterName, $bytes)
if ($ok) { Write-Output "PRINTED" } else { Write-Output "FAILED"; exit 1 }
