param([Parameter(Mandatory=$true)][string]$RuntimeInstaller)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $RuntimeInstaller
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw "Microsoft WebView2 signature rejected: $($signature.Status) $($signature.StatusMessage)"
}
Write-Output 'Microsoft WebView2 signature verified.'
