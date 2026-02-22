# ZeroWall — DGX Spark Setup Guide (Fresh System)

Complete setup from a blank NVIDIA DGX Spark to running the full demo.

---

## 1. System Prerequisites

### 1.1 Update the OS
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git wget build-essential python3-pip python3-venv unzip jq
```

### 1.2 Verify GPU Access
```bash
nvidia-smi
# You should see your DGX Spark GPU(s) listed
# If not: sudo apt install -y nvidia-driver-535
```

---

## 2. Install Docker + NVIDIA Container Toolkit

Docker is required to run Triton Inference Server and vLLM.

### 2.1 Install Docker
```bash
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker $USER
newgrp docker          # Apply group without logout
docker run hello-world # Verify
```

### 2.2 Install NVIDIA Container Toolkit
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU is accessible in containers
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### 2.3 Install Docker Compose v2
```bash
sudo apt install -y docker-compose-plugin
docker compose version   # Should show v2.x
```

---

## 3. Clone the ZeroWall Repo

```bash
cd ~
git clone <your-repo-url> ZeroWall
cd ZeroWall
```

> **If transferring from your Mac:** `scp -r /Users/damienjohnson/Desktop/Code/Nullcondition/ZeroWall dgx-user@<DGX_IP>:~/ZeroWall`

---

## 4. Configure Environment

```bash
cp .env.example .env
nano .env   # Or: vim .env
```

**Minimum required edits in `.env`:**

| Variable | What to set |
|----------|-------------|
| `HF_TOKEN` | Your Hugging Face token from [hf.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `VLLM_MODEL` | `microsoft/phi-2` (small, fast) or `mistralai/Mistral-7B-Instruct-v0.1` |
| `VLLM_TP_SIZE` | Number of GPUs to use for tensor parallelism (1 for single GPU) |
| `RAPIDS_ENABLED` | `true` (DGX Spark has RAPIDS) |
| `MODEL_CACHE_DIR` | `/home/$USER/.cache/huggingface` (or a fast NVMe path) |

```bash
# Quick defaults that work with 1 GPU:
cat > .env << 'EOF'
TARGET_PORT=8000
APP_VERSION=v1.0.0-ORIGINAL
DEPLOY_HASH=aabbcc001122
TRITON_HTTP_PORT=8080
TRITON_GRPC_PORT=8081
TRITON_METRICS_PORT=8082
VLLM_PORT=8088
VLLM_MODEL=microsoft/phi-2
VLLM_TP_SIZE=1
HF_TOKEN=YOUR_HF_TOKEN_HERE
MODEL_CACHE_DIR=/home/$USER/.cache/huggingface
OPENCLAW_PORT=9000
DASHBOARD_PORT=8501
RAPIDS_ENABLED=true
MUTATION_CANDIDATE_COUNT=10
EXPLOIT_WORKERS=4
BENCHMARK_BURST_SIZE=50
BENCHMARK_CONCURRENCY=8
EOF
# Then edit to add your HF token:
nano .env
```

---

## 5. Install RAPIDS (cuDF)

RAPIDS is the GPU DataFrame library. Install it on the host for running Python scripts directly.

```bash
# Recommended: use the RAPIDS conda installer
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
source $HOME/miniconda3/bin/activate

# Create a RAPIDS environment (CUDA 12.x, Python 3.11)
conda create -n zerowall -c rapidsai -c conda-forge -c nvidia \
  rapids=24.02 python=3.11 cuda-version=12.2 -y

conda activate zerowall
```

### 5.1 Install remaining Python deps
```bash
conda activate zerowall
pip install -r requirements.core.txt
pip install streamlit   # For dashboard
```

### 5.2 Verify RAPIDS
```bash
python -c "import cudf; print('cuDF version:', cudf.__version__)"
# Should print: cuDF version: 24.02.x
```

---

## 6. Set Up the Target App Python Environment

```bash
cd ~/ZeroWall/apps/target-fastapi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 6.1 Run the unit tests (verify the app works)
```bash
python -m pytest test_app.py -v
# Expected: 28 passed
```

```
deactivate
cd ~/ZeroWall
```

---

## 7. Pull Docker Images

These are large — pull them before the demo.

```bash
# Triton Inference Server (~10 GB)
docker pull nvcr.io/nvidia/tritonserver:24.01-py3

# vLLM (~8 GB)
docker pull vllm/vllm-openai:latest
```

> **Note:** `nvcr.io` requires free NVCR credentials if you hit auth errors:
> ```bash
> docker login nvcr.io
> # Username: $oauthtoken
> # Password: <your NGC API key from ngc.nvidia.com>
> ```

---

## 8. Start All Services (Docker Compose)

```bash
cd ~/ZeroWall
docker compose up -d
```

**Wait for health checks** — Triton takes ~30–60s to load:
```bash
watch docker compose ps
# All services should show "healthy" before continuing
```

### Verify each service:
```bash
# Target app
curl http://localhost:8000/health

# Triton
curl http://localhost:8080/v2/health/ready

# vLLM
curl http://localhost:8088/health

# Dashboard (open in browser)
# http://<DGX_IP>:8501
```

---

## 9. Run ZeroWall Tests End-to-End

### 9.1 Verify the exploit works on the vulnerable app
```bash
bash scripts/seed_attack.sh
# Look for: X-ZeroWall-Alert: SUSPICIOUS in the response headers
# And response body showing exploit "succeeded" (status: unknown, SIMULATED)
```

### 9.2 Open the OpenClaw CLI (interactive demo mode)
```bash
conda activate zerowall
cd ~/ZeroWall
export PYTHONPATH=~/ZeroWall
export TARGET_URL=http://localhost:8000
export TRITON_HOST=localhost
export TRITON_HTTP_PORT=8080
export VLLM_HOST=localhost
export VLLM_PORT=8088

python -m core.orchestrator.openclaw_cli interactive
```

**Type these commands in the interactive session:**
```
/simulate-alert      ← inject mock IDS alert
/defend              ← run full defense cycle (takes ~10–30s)
/status              ← check what was deployed
/replay              ← verify exploit is now blocked
```

### 9.3 Run the benchmark
```bash
bash scripts/run_benchmark.sh
# Results saved to: artifacts/benchmark/benchmark_summary.json
cat artifacts/benchmark/benchmark_summary.json
```

### 9.4 Full automated demo flow
```bash
bash scripts/run_demo.sh
```

---

## 10. Open the Streamlit Dashboard

```bash
# If running scripts locally (not Docker):
conda activate zerowall
streamlit run dashboard/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Open in browser: `http://<DGX_IP>:8501`

---

## 11. Troubleshooting

### Triton fails to start
```bash
docker compose logs triton
# Common fix: ensure model repo path is mounted correctly
ls -la inference/triton-model-repo/
# Should contain: mutation-planner/  risk-scorer/
```

### vLLM OOM error
```bash
# Reduce model size or enable quantization in .env:
# VLLM_MODEL=microsoft/phi-2  (smaller)
# Or add to vllm command in docker-compose.yml:
# --quantization awq
```

### RAPIDS import error outside Docker
```bash
# Make sure you're in the conda env:
conda activate zerowall
python -c "import cudf"
```

### Scripts permission denied
```bash
chmod +x scripts/*.sh
```

### Port already in use
```bash
sudo lsof -i :8000   # Find what's using the port
# Or change ports in .env
```

---

## 12. Collect GPU Evidence for Judges

```bash
# Live GPU utilization during benchmark:
nvidia-smi dmon -s u -d 1 | tee artifacts/gpu_utilization.txt &
bash scripts/run_benchmark.sh
kill %1   # Stop monitoring

# Or get a snapshot:
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total \
  --format=csv | tee artifacts/gpu_snapshot.csv
```

Take a screenshot of `nvidia-smi` output during the defense cycle for your submission.

---

## Quick Reference: Key URLs

| Service | URL |
|---------|-----|
| Target App | `http://localhost:8000` |
| Target App Docs | `http://localhost:8000/docs` |
| Triton HTTP | `http://localhost:8080` |
| Triton Metrics | `http://localhost:8082/metrics` |
| vLLM API | `http://localhost:8088/v1` |
| Streamlit Dashboard | `http://localhost:8501` |

## Quick Reference: Key Files

| File | Purpose |
|------|---------|
| `.env` | All configuration |
| `scripts/run_demo.sh` | Full demo flow |
| `scripts/seed_attack.sh` | Fire exploit payloads |
| `scripts/run_benchmark.sh` | Benchmark mode |
| `artifacts/benchmark/benchmark_summary.json` | Benchmark output |
| `telemetry_data/telemetry.jsonl` | RAPIDS analytics input |
