#!/bin/bash
# One-time VPS setup script for flattrade

# --- 1. Update system ---
echo "[1/7] Updating system..."
apt update && apt upgrade -y

# --- 2. Install required packages ---
echo "[2/7] Installing Python, pip, git..."
apt install -y python3 python3-pip python3-venv git

# --- 3. Set timezone to IST ---
echo "[3/7] Setting timezone to IST..."
timedatectl set-timezone Asia/Kolkata
timedatectl

# --- 4. Clone repo ---
REPO_DIR="/root/flattrade2026"
REPO_URL="https://github.com/AnkitxRai/flattrade.git"
if [ -d "$REPO_DIR" ]; then
    echo "[4/7] Repo exists, pulling latest changes..."
    cd "$REPO_DIR" && git pull
else
    echo "[4/7] Cloning repo..."
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

# --- 5. Install Python dependencies ---
echo "[5/7] Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install --break-system-packages -r requirements.txt
else
    pip3 install --break-system-packages pyotp
fi

# --- 6. Test script once ---
echo "[6/7] Running script once for testing..."
cd "$REPO_DIR"
nohup python3 webcoipcr.py > webcoipcr.log 2>&1 &
sleep 5
pkill -f webcoipcr.py
echo "Test run completed. Check $REPO_DIR/webcoipcr.log for output."

# --- 7. Setup cron ---
echo "[7/7] Setting up cron jobs..."
(crontab -l 2>/dev/null; echo "") | crontab - # ensure crontab exists
CRON_ENTRY="CRON_TZ=Asia/Kolkata
45 9 * * 1-5 cd /root/flattrade2026 && nohup python3 webcoipcr.py > /root/flattrade2026/webcoipcr.log 2>&1 &
15 15 * * 1-5 pkill -f webcoipcr.py"
echo "$CRON_ENTRY" | crontab -

echo "✅ Setup complete! Cron jobs added. Script will run automatically on weekdays."