###############################################################################
#  
#  Carelink Client 2 library
#  
#  Description:
#
#    This library implements a client for the Medtronic Carelink API
#    as used by the official Carelink Connect Android app.
#  
#  Author:
#
#    Ondrej Wisniewski (ondrej.wisniewski *at* gmail.com)
#  
#  Changelog:
#
#    28/12/2023 - Initial version
#
#  Copyright 2023, Ondrej Wisniewski 
#
###############################################################################

import json
import requests
import time
import base64
import logging as log
from datetime import datetime, timedelta


# Workflow
# --------
#
# [0.1] GET access_token, refresh_token, mag-identifier from login procedure
# carelink_carepartner_api_login.py
#
# [0.2] GET base_urls (region=US or region=EU) and sso_config urls
# GET https://clcloud.minimed.eu/connect/carepartner/v6/discover/android/3.1
#
# [1] GET role from "baseUrlCareLink"
# GET /api/carepartner/v2/users/me
#
# [2] GET patientId from "baseUrlCareLink"
# GET /api/carepartner/v2/links/patients
#
# [3] GET data (providing username, role, patientId) from "baseUrlCumulus"
# POST /connect/carepartner/v6/display/message
#
# [4] REFRESH access_token, refresh_token from 
# sso_config['server']['hostname']:sso_config['server']['port']/sso_config['server']['prefix']/sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]
# POST /auth/oauth/v2/token
 
# Version string
VERSION = "0.1"

# DEBUG
ACCESSTOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6ImRlZmF1bHRfc3NsX2tleSJ9.ew0KICAiaXNzIjogImh0dHBzOi8vbWR0c3RzLW9jbC5tZWR0cm9uaWMuY29tL21tY2wiLA0KICAiaWF0IjoxNzAzNzc2NTg1LA0KICAiYXVkIjoiYzE5MjE4ZjItNzE1Ny00YzkzLThmYmUtNDk2MzZlN2Y5Yzc0IiwNCiAgImV4cCI6MTcwMzc4NzU2NSwNCiAgInN1YiI6IklUYlJlcDNKQldEWVhoZ2NES1pQSmxHVUY2N201VThnWXVCeEJ0djlrOGsiLA0KICAianRpIjoiYzcxZTE3MGItOGFmNi00NTY3LTk2MDAtOTI2ZDIxODI5ZDQxIiwNCiAgInRva2VuX2RldGFpbHMiOiB7DQogICAgInNjb3BlIjoicHJvZmlsZSBvcGVuaWQgcm9sZXMgY291bnRyeSBtc3NvIG1zc29fcmVnaXN0ZXIgbXNzb19jbGllbnRfcmVnaXN0ZXIiLA0KICAgICJleHBpcmVzX2luIjoxMDk4MCwNCiAgICAidG9rZW5fdHlwZSI6IkJlYXJlciIsDQoicHJlZmVycmVkX3VzZXJuYW1lIjoib25kcmVqMjAyMyIsDQoibmFtZSI6IkplcmRubyBJa3N3ZWluc2l3IiwNCiJnaXZlbl9uYW1lIjoiSmVyZG5vIiwNCiJmYW1pbHlfbmFtZSI6Iklrc3dlaW5zaXciLA0KImxvY2FsZSI6ImVuIiwNCiJjb3VudHJ5IjogIklUIiwNCiJyb2xlcyI6WyJjYXJlX3BhcnRuZXJfb3VzIl0NCiAgfQ0KfQ.b9arU3YYByYHudXy9ixVF1MuUSz-oeHepBnT-IX3ooA9jUrF7Id7j4r-iBS8m1q6im_zA57HbHVwzphm_auUCkN1TvbfTtGsqoNNnEsGU4MWDNae1FdcLHhQImbQPGhjro-TVbh2Tw1ge6470yxJ_Yl3--lKYVj2v55-Y-L6dJpQwA5W3OpJPz8ojtsyqRgaQY_uiVovGKEybgezyPqPfUjAclHKa1mDMGTpdfGbS-Sg-l4PEW0vtA_rZvIeO_vcHRRQlAwL95BAmC__DGw5CayimS50Qg42Z3OSf_QABIP2dI6oxJZkaHu7D0fTEEKeiYfoFKmSISOecSV2zmgmuQ"
REFRESHTOKEN="04663336-83e2-4b06-bfd3-6c319e416f50"
MAGIDENTIFIER="VEh6UUZzanBuR0lsVUhGYVBpZDZUdkN1dlo4PQ=="
USERNAME="ondrej2023"

# Constants
CARELINK_CONFIG_URL = "https://clcloud.minimed.eu/connect/carepartner/v6/discover/android/3.1"


class CareLinkClient2(object):
   
   def __init__(self, accessToken=None, refreshToken=None, magIdentifier=None, userName=None):
      
      self.__version = VERSION
      
      # Authorization
      self.__accessToken = accessToken
      self.__refreshToken = refreshToken
      self.__magIdentifier = magIdentifier
      
      # API config
      self.__config = None
      #self.__api_base_url = None
      
      # User info
      self.__username = userName
      self.__role = None
      self.__patient = None
      #self.__carelinkCountry = carelinkCountry.lower() if carelinkCountry else None
      #self.__carelinkPatient = carelinkPatient
      
      self.__commonHeaders = {
         "Accept": "application/json",
         "Content-Type": "application/json",
         "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; Nexus 5X Build/QQ3A.200805.001)",
         }

   def _get_config(self, config_url, is_us_region=None):
      config_resp = requests.get(config_url).json()
      config = None

      for c in config_resp["CP"]:
         if c['region'].lower() == "us" and is_us_region:
            config = c
         elif c['region'].lower() == "eu" and not is_us_region:
            config = c
		
      if config is None:
         raise Exception("Could not get config base urls")

      #sso_config = requests.get(sso_url).json()
      #api_base_url = f"https://{sso_config['server']['hostname']}:{sso_config['server']['port']}/{sso_config['server']['prefix']}"
      return config
   
   def _get_role(self, config, magIdentifier, accessToken):
      url = config["baseUrlCareLink"] + "/users/me"
      headers = self.__commonHeaders
      headers["mag-identifier"] = magIdentifier
      headers["Authorization"] = "Bearer " + accessToken
      resp = requests.get(url=url,headers=headers).json()
      role = resp["role"]
      return role

   def _get_patient(self, config, magIdentifier, accessToken):
      url = config["baseUrlCareLink"] + "/links/patients"
      headers = self.__commonHeaders
      headers["mag-identifier"] = magIdentifier
      headers["Authorization"] = "Bearer " + accessToken
      resp = requests.get(url=url,headers=headers).json()
      patient = resp[0]
      return patient

   def _get_data(self, config, magIdentifier, accessToken, username, role, patientid):
      url = config["baseUrlCumulus"] + "/display/message"
      headers = self.__commonHeaders
      headers["mag-identifier"] = magIdentifier
      headers["Authorization"] = "Bearer " + accessToken
      data = {
         "username":username,
         "role":"carepartner" if role in ["CARE_PARTNER","CARE_PARTNER_OUS"] else "patient",
         "patientId":patientid
         }
      #print("url: %s" % url)
      #print("headers: %s" % json.dumps(headers))
      #print("data: %s" % json.dumps(data))
      resp = requests.post(url=url,headers=headers,data=json.dumps(data))
      print("status: %d" % resp.status_code)
      return resp.json()

   def init(self):
      self.__config = self._get_config(CARELINK_CONFIG_URL)
      print(json.dumps(self.__config))
      self.__role = self._get_role(self.__config, self.__magIdentifier, self.__accessToken)
      print(self.__role)
      self.__patient = self._get_patient(self.__config, self.__magIdentifier, self.__accessToken)
      print(json.dumps(self.__patient))
      
   def getRecentData(self):
      return self._get_data(self.__config, 
                            self.__magIdentifier, 
                            self.__accessToken, 
                            self.__username,
                            self.__role,
                            self.__patient["username"])


# MAIN (TEST)

clc2 = CareLinkClient2(ACCESSTOKEN, REFRESHTOKEN, MAGIDENTIFIER, USERNAME)
clc2.init()
data = clc2.getRecentData()
#print(json.dumps(data))
