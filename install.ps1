# 把本仓库安装为 WorkBuddy Skill（Windows PowerShell）
#
# 用法：
#   .\install.ps1              # 软链（需开发者模式或管理员），失败自动改复制
#   .\install.ps1 -Copy        # 强制复制
#   .\install.ps1 -Uninstall   # 卸载（移到 .trash，不直接删除）
#
# 安全说明：本脚本永不做递归删除。
# 覆盖或卸载时一律把原有目录【移到 .trash\ 下带时间戳的目录】，可随时找回。
param(
    [switch]$Copy,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Src       = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillsDir = Join-Path $env:USERPROFILE ".workbuddy\skills"
$Dest      = Join-Path $SkillsDir "mcd-ordering"
$Trash     = Join-Path $SkillsDir ".trash"
$Stamp     = Get-Date -Format "yyyyMMdd-HHmmss"

function Backup-Existing {
    if (Test-Path $Dest) {
        if (-not (Test-Path $Trash)) {
            New-Item -ItemType Directory -Path $Trash -Force | Out-Null
        }
        $dst = Join-Path $Trash "mcd-ordering-$Stamp"
        $i = 1
        while (Test-Path $dst) {
            $dst = Join-Path $Trash "mcd-ordering-$Stamp-$i"
            $i++
        }
        Move-Item $Dest $dst -Force
        Write-Host "原有目录已移到：$dst" -ForegroundColor DarkYellow
    }
}

if ($Uninstall) {
    if (Test-Path $Dest) {
        Backup-Existing
        Write-Host "已卸载（可从 $Trash 找回）" -ForegroundColor Green
    } else {
        Write-Host "未安装：$Dest"
    }
    exit 0
}

if (-not (Test-Path (Join-Path $Src "SKILL.md"))) {
    Write-Host "缺少 SKILL.md，请在仓库根目录运行" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $Src "scripts"))) {
    Write-Host "缺少 scripts/，请在仓库根目录运行" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $SkillsDir)) {
    New-Item -ItemType Directory -Path $SkillsDir -Force | Out-Null
}
Backup-Existing

$Items = @("SKILL.md", "README.md", "scripts", "references", "assets", "config")

function Copy-Payload {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    foreach ($item in $Items) {
        $s = Join-Path $Src $item
        if (Test-Path $s) {
            Copy-Item $s -Destination $Dest -Recurse -Force
        }
    }
}

if ($Copy) {
    Copy-Payload
    Write-Host "已复制到：$Dest" -ForegroundColor Green
} else {
    try {
        New-Item -ItemType SymbolicLink -Path $Dest -Target $Src | Out-Null
        Write-Host "已软链：$Dest -> $Src" -ForegroundColor Green
    } catch {
        Write-Host "软链失败（需开发者模式），自动改用复制…" -ForegroundColor Yellow
        Copy-Payload
        Write-Host "已复制到：$Dest" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "安装完成。接下来：" -ForegroundColor Green
Write-Host "  1. 重启 WorkBuddy 会话（skill 在会话启动时加载）"
Write-Host "  2. 配置 MCP：把 mcp-config.example.json 里的 mcd-mcp 段落"
Write-Host "     合并到 ~/.workbuddy/mcp.json，填入自己的 Bearer token"
Write-Host "  3. 自检："
Write-Host "       python scripts/dice_roll.test.py --offline"
Write-Host "       python tests/pay.test.py"
Write-Host ""
Write-Host "卸载：.\install.ps1 -Uninstall （只移到 .trash，不删除）"
