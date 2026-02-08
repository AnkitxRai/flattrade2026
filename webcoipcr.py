from collections import UserDict
from NorenWebApi import NorenWebApi

userid = "FZ19246"
password = "##"
totp_secret = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key = "" # login on web and copy from network tab : quickauth api


# userid = "FZ31096"
# password = "##"
# totp_secret = "V3B3T3AZ3U6236HO35BQRL6S4KP725O5"
# app_key = "" # login on web and copy from network tab : quickauth api


api = NorenWebApi()
api.login(userid=userid, password=password, totp_secret=totp_secret,app_key=app_key)


dd = api.get_order_book()
print(dd)
