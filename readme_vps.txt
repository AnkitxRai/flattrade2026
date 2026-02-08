Automatic Setup VPS


clone vps_setup.sh
chmod +x vps_setup.sh
sudo ./vps_setup.sh



===============================
Manual Setup VPS

apt update && apt upgrade -y
apt install python3 -y
apt install python3-pip -y
git clone https://github.com/AnkitxRai/flattrade.git
pip3 install pyotp --break-system-packages
timedatectl
timedatectl set-timezone Asia/Kolkata

---------------------------------


# setup cron
1. crontab -e
2. Add these two lines at bottom to start script 9:45 am - 3:15 pm
```
45 9 * * 1-5 cd /root/flattrade && nohup python3 flat_vwap_api.py > flat_vwap.log 2>&1 &
15 15 * * 1-5 pkill -f flat_vwap_api.py
```

# verify cron
crontab -l
systemctl status cron


---------------------------------



# if want to test cron manually

cd /root/flattrade
nohup python3 flat_vwap_api.py > flat_vwap.log 2>&1 &
ps aux | grep flat_vwap_api.py
tail -f flat_vwap.log

# stop after checking
pkill -f flat_vwap_api.py


----------------------------------