#!/usr/bin/env bash
# ============================================================
#  Militech Open Bot — установка и запуск на Linux
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }

if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}[ERR] Не запускайте от root.${NC}"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Обновляем список пакетов..."
sudo apt-get update -qq

info "Устанавливаем системные зависимости..."
sudo apt-get install -y python3 python3-pip python3-venv python3-tk python3-dev python3-xlib \
    scrot xclip xdotool libxcb-cursor0 libatk-bridge2.0-0 libgtk-3-0 libjpeg-dev zlib1g-dev \
    libpng-dev libfreetype6-dev libtiff-dev libwebp-dev sqlite3 2>/dev/null || warn "Часть пакетов пропущена"

VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" --system-site-packages
fi
source "$VENV_DIR/bin/activate"

info "Обновляем pip..."
pip install --upgrade pip wheel setuptools -q

info "Устанавливаем Python-зависимости..."
pip install -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || warn "Ошибки при установке некоторых пакетов pip"

RUN_SCRIPT="$SCRIPT_DIR/run.sh"
cat > "$RUN_SCRIPT" << 'RUNEOF'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"
exec python3 run.py "$@"
RUNEOF
chmod +x "$RUN_SCRIPT"

success "Установка завершена!"
echo "Для запуска графического интерфейса: ./run.sh"
echo "Для запуска без графики: ./run.sh --headless"