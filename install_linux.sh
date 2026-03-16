#!/usr/bin/env bash
# ============================================================
#  Militech Open Bot — установка и запуск на Linux
# ============================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()     { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

if [ "$EUID" -eq 0 ]; then
    err "Не запускайте от root."
fi

# Проверка версии Python (нужен 3.10+)
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
    err "python3 не найден. Установите Python 3.10+."
fi
PY_VER=$("$PY" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
PY_MAJOR=$("$PY" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_VER" -lt 10 ]; then
    err "Требуется Python 3.10+, найден $PY_MAJOR.$PY_VER."
fi
info "Python $PY_MAJOR.$PY_VER — OK"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Обновляем список пакетов..."
sudo apt-get update -qq

info "Устанавливаем системные зависимости..."
sudo apt-get install -y \
    python3 python3-pip python3-venv python3-tk python3-dev \
    python3-xlib scrot xclip xdotool \
    libxcb-cursor0 libatk-bridge2.0-0 libgtk-3-0 \
    libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev \
    libtiff-dev libwebp-dev \
    libssl-dev libffi-dev \
    sqlite3 \
    || warn "Часть системных пакетов пропущена"

VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Создаём виртуальное окружение..."
    python3 -m venv "$VENV_DIR" --system-site-packages
fi

source "$VENV_DIR/bin/activate"

info "Обновляем pip..."
pip install --upgrade pip wheel setuptools -q

info "Устанавливаем Python-зависимости..."
pip install -r "$SCRIPT_DIR/requirements.txt" \
    || warn "Ошибки при установке некоторых pip-пакетов (см. выше)"

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
echo ""
echo "  Графический интерфейс:  ./run.sh"
echo "  Без графики (сервер):   ./run.sh --headless"