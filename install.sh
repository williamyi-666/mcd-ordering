#!/usr/bin/env bash
# 把本仓库安装为 WorkBuddy Skill（macOS / Linux / Git Bash）
#
# 用法：
#   ./install.sh              # 软链到 ~/.workbuddy/skills/mcd-ordering
#   ./install.sh --copy       # 复制而非软链（跨盘/权限受限时用）
#   ./install.sh --uninstall  # 卸载（移到回收目录，不直接删除）
#
# 安全说明：本脚本永不做 `rm -rf` 式删除。
# 覆盖或卸载时一律把原有目录【移到 .trash/ 下带时间戳的目录】，可随时找回。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.workbuddy/skills"
DEST="$SKILLS_DIR/mcd-ordering"
TRASH="$SKILLS_DIR/.trash"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
MODE="link"

backup_existing() {
  if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    mkdir -p "$TRASH"
    local dst="$TRASH/mcd-ordering-$STAMP"
    mv "$DEST" "$dst"
    echo "原有目录已移到：$dst"
  fi
}

for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    --uninstall)
      if [ -e "$DEST" ] || [ -L "$DEST" ]; then
        backup_existing
        echo "已卸载（可从 $TRASH 找回）"
      else
        echo "未安装：$DEST"
      fi
      exit 0
      ;;
    -h|--help)
      sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "未知参数：$arg"; exit 2 ;;
  esac
done

# 基本体检
[ -f "$SRC/SKILL.md" ] || { echo "缺少 SKILL.md，请在仓库根目录运行"; exit 1; }
[ -d "$SRC/scripts" ]  || { echo "缺少 scripts/，请在仓库根目录运行"; exit 1; }

mkdir -p "$SKILLS_DIR"
backup_existing

if [ "$MODE" = "link" ]; then
  ln -s "$SRC" "$DEST"
  echo "已软链：$DEST -> $SRC"
else
  mkdir -p "$DEST"
  for item in SKILL.md README.md scripts references assets config; do
    [ -e "$SRC/$item" ] && cp -R "$SRC/$item" "$DEST/" || true
  done
  echo "已复制到：$DEST"
fi

cat <<'TIP'

安装完成。接下来：

1. 重启 WorkBuddy 会话（skill 在会话启动时加载）
2. 配置 MCP：把 mcp-config.example.json 里的 mcd-mcp 段落
   合并到 ~/.workbuddy/mcp.json，填入自己的 Bearer token
3. 自检：
     python scripts/dice_roll.test.py --offline    # 骰子引擎（75 项）
     python tests/pay.test.py                      # 付款闭环（20 项）

卸载：./install.sh --uninstall （只移到 .trash，不删除）
TIP
