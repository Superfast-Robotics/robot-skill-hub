param(
    [string]$GithubTokenFile = "$PSScriptRoot\..\.local\github-bot-token.secret",
    [string]$PrincipalId = 'pilot-1'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath "$PSScriptRoot\..").Path
$localDir = Join-Path $root '.local'
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
if (Test-Path -LiteralPath $GithubTokenFile) {
    $botToken = (Get-Content -LiteralPath $GithubTokenFile -Raw).Trim()
} else {
    $secureToken = Read-Host 'Paste the repo-scoped GitHub fine-grained token (hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try { $botToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
if ([string]::IsNullOrWhiteSpace($botToken)) { throw 'No token supplied.' }
$headers = @{ Authorization = "Bearer $botToken"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
$repo = Invoke-RestMethod -Uri 'https://api.github.com/repos/Superfast-Robotics/robot-skill-hub' -Headers $headers
if ($repo.full_name -ne 'Superfast-Robotics/robot-skill-hub') { throw 'Unexpected repository.' }
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$pilotToken = 'rsh_' + [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pilotToken)) | ForEach-Object { $_.ToString('x2') }) }
finally { $sha.Dispose() }
$principals = ConvertTo-Json -InputObject @(@{ principal_id = $PrincipalId; sha256 = $hash }) -Compress
Push-Location (Join-Path $root 'api')
try {
    $botToken | & npx.cmd wrangler secret put GITHUB_TOKEN
    if ($LASTEXITCODE -ne 0) { throw 'GitHub Worker secret upload failed.' }
    $principals | & npx.cmd wrangler secret put SUBMISSION_TOKENS_JSON
    if ($LASTEXITCODE -ne 0) { throw 'Submission secret upload failed.' }
} finally { Pop-Location; $botToken = $null }
$utf8 = New-Object Text.UTF8Encoding $false
[IO.File]::WriteAllText((Join-Path $localDir 'pilot-token.secret'), $pilotToken, $utf8)
[IO.File]::WriteAllText((Join-Path $localDir 'pilot-env.ps1'), ('$env:RSH_API_URL = ''https://api.superfastrobotics.com''' + [Environment]::NewLine + '$env:RSH_SUBMISSION_TOKEN = (Get-Content -LiteralPath (Join-Path $PSScriptRoot ''pilot-token.secret'') -Raw).Trim()' + [Environment]::NewLine), $utf8)
$pilotToken = $null
Write-Output 'Worker secrets configured. Pilot token: .local/pilot-token.secret (ignored by Git).'
Write-Output 'Load client environment: . .\.local\pilot-env.ps1'
