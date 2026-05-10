#!/usr/bin/env bash
set -e

echo "==> ApexForge Swarm Setup"

# Check Python
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

# Create venv
echo "==> Creating virtual environment..."
python3 -m venv .venv

# Activate
source .venv/bin/activate

# Install deps
echo "==> Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Copy env
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "==> Created .env (edit if needed)"
fi

echo ""
echo "Setup complete!"
echo ""
echo "  Activate:   source .venv/bin/activate"
echo "  CLI:        python main.py"
echo "  Web UI:     python main.py --web"
echo "  Desktop:    python main.py --desktop"
echo "  Other model: python main.py --model qwen2.5-7b-instruct-q4_k_m.gguf"
echo "  LLM backend: edit .env and set LLM_PROVIDER=ollama or LLM_PROVIDER=llama_cpp"
echo ""
