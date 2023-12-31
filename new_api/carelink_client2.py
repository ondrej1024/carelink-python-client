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

import json
import requests
import time
import base64
import os
import logging as log
from datetime import datetime, timedelta

 
# Version string
VERSION = "1.0"

# Constants
DEFAULT_FILENAME="logindata.json"
CARELINK_CONFIG_URL = "https://clcloud.minimed.eu/connect/carepartner/v6/discover/android/3.1"
AUTH_ERROR_CODES = [401,403]
COMMON_HEADERS = {
                  "Accept": "application/json",
                  "Content-Type": "application/json",
                  "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; Nexus 5X Build/QQ3A.200805.001)",
                 }

# Logging config
FORMAT = '[%(asctime)s:%(levelname)s] %(message)s'
log.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S', level=log.DEBUG)


###########################################################
# Class CareLinkClient
###########################################################
class CareLinkClient(object):
   
   def __init__(self, tokenFile=DEFAULT_FILENAME, userName=None):
      
      self.__version = VERSION
      
      # Authorization
      self.__tokenFile = tokenFile
      self.__tokenData = self._read_token_file(self.__tokenFile)
      
      # API config
      self.__config = None
      
      # User info
      self.__username = userName
      self.__role = None 
      self.__patient = None 
      
      # API status
      self.__last_api_status = None
      
   ###########################################################
   # Class internal functions
   ###########################################################
   
   ###########################################################
   # Read token file
   ###########################################################
   def _read_token_file(self, filename):
      log.debug("_read_token_file()")
      token_data = None
      if os.path.isfile(filename):
         try:
            token_data = json.loads(open(filename, "r").read())
         except json.JSONDecodeError:
            log.debug("   failed parsing json")

         if token_data is not None:
            required_fields = ["access_token", "refresh_token", "scope", "client_id", "client_secret", "mag-identifier"]
            for f in required_fields:
               if f not in token_data:
                  log.debug("   field %s is missing from data file" % f)
                  return None
      return token_data

   ###########################################################
   # Write token file
   ###########################################################
   def _write_token_file(self, obj, filename):
      log.debug("_write_token_file()")
      with open(filename, 'w') as f:
         json.dump(obj, f, indent=4)

   def _get_config(self, config_url, is_us_region=None):
      log.debug("_get_config()")
      resp = requests.get(config_url)
      log.debug("   status: %d" % resp.status_code)
      config = None

      for c in resp.json()["CP"]:
         if c["region"].lower() == "us" and is_us_region:
            config = c
         elif c["region"].lower() == "eu" and not is_us_region:
            config = c
		
      if config is None:
         raise Exception("Could not get config base urls")

      resp = requests.get(config["SSOConfiguration"])
      log.debug("   status: %d" % resp.status_code)
      sso_config = resp.json()
      sso_base_url = f"https://{sso_config['server']['hostname']}:{sso_config['server']['port']}/{sso_config['server']['prefix']}"
      token_url = sso_base_url + sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]
      c["token_url"] = token_url
      return config
   
   ###########################################################
   # Get users Carelink role
   ###########################################################
   def _get_role(self, config, token_data):
      log.debug("_get_role()")
      url = config["baseUrlCareLink"] + "/users/me"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      self.__last_api_status = None
      resp = requests.get(url=url,headers=headers)
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      role = resp.json()["role"]
      return role

   ###########################################################
   # Get patient data
   ###########################################################
   def _get_patient(self, config, token_data):
      log.debug("_get_patient()")
      url = config["baseUrlCareLink"] + "/links/patients"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      self.__last_api_status = None
      resp = requests.get(url=url,headers=headers)
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      patient = resp.json()[0]
      return patient

   ###########################################################
   # Get periodic pump and sensor data
   ###########################################################
   def _get_data(self, config, token_data, username, role, patientid):
      log.debug("_get_data()")
      url = config["baseUrlCumulus"] + "/display/message"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      data = {
         "username":username,
         "role":"carepartner" if role in ["CARE_PARTNER","CARE_PARTNER_OUS"] else "patient",
         "patientId":patientid
         }
      #log.debug("url: %s" % url)
      #log.debug("headers: %s" % json.dumps(headers))
      #log.debug("data: %s" % json.dumps(data))
      self.__last_api_status = None
      resp = requests.post(url=url,headers=headers,data=json.dumps(data))
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      return resp.json()

   ###########################################################
   # Do token data refresh
   ###########################################################
   def _do_refresh(self, config, token_data):
      log.debug("_do_refresh()")
      token_url = config["token_url"]
      data = {
         "refresh_token": token_data["refresh_token"],
         "client_id":     token_data["client_id"],
         "client_secret": token_data["client_secret"],
         "grant_type":    "refresh_token"
         }
      headers = {
         "mag-identifier": token_data["mag-identifier"]
         }
      resp = requests.post(url=token_url, headers=headers, data=data)
      log.debug("   status: %d" % resp.status_code)
      new_data = resp.json()
      token_data["access_token"] = new_data["access_token"]
      token_data["refresh_token"] = new_data["refresh_token"]
      return token_data

   ###########################################################
   # Check access token validity
   ###########################################################
   def _is_token_valid(self, token_data):
      log.debug("_is_token_valid()")
      try:
         token = token_data["access_token"]
      except:
         log.debug("   no access token found")
         return False
      try:
         # Decode json web token payload
         payload_b64 = token.split('.')[1]
         payload_b64_bytes = payload_b64.encode()
         missing_padding = (4 - len(payload_b64_bytes) % 4) % 4
         if missing_padding:
            payload_b64_bytes += b'=' * missing_padding
         payload_bytes = base64.b64decode(payload_b64_bytes)
         payload = payload_bytes.decode()
         payload_json = json.loads(payload)
         #log.debug(payload_json)
         
         # Get expiration time stamp
         token_validto = payload_json["exp"]
      except:
         log.debug("   malformed access token")
         return False
      
      # Check expiration time stamp
      tdiff = token_validto - time.time()
      if tdiff < 0:
         log.debug("   access token has expired %ds ago" % abs(tdiff))
         return False
      if tdiff < 600:
         log.debug("   access token is about to expire in %ds" % abs(tdiff))
         return False
      
      # Token is valid
      auth_token_validto = datetime.utcfromtimestamp(token_validto).strftime('%a %b %d %H:%M:%S UTC %Y')
      log.debug("   access token expires in %ds (%s)" % (tdiff,auth_token_validto))
      return True

   ###########################################################
   # Init static data
   ###########################################################
   def _init(self):
      try:
         self.__config = self._get_config(CARELINK_CONFIG_URL)
         self.__role = self._get_role(self.__config, self.__tokenData)
         self.__patient = self._get_patient(self.__config, self.__tokenData)
      except:
         if self.__last_api_status in [401,403]:
            self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
            self._write_token_file(self.__tokenData, self.__tokenFile)
            return False
      return True


   ###########################################################
   # Class public functions
   ###########################################################

   ###########################################################
   # Init object
   ###########################################################
   def init(self):
      # First try
      if self._init() == False:
         # Second try (after token refresh)
         if self._init() == False:
            # Failed permanently
            print("ERROR: unable to initialize")
            return False
      return True
      
   ###########################################################
   # Print user info
   ###########################################################
   def printUserInfo(self):
      print("User Info:")
      print("   username: %s" % self.__username)
      print("   role:     %s" % self.__role)
      print("   patient:  %s (%s %s)" % (self.__patient["username"],self.__patient["firstName"],self.__patient["lastName"]))
            
   ###########################################################
   # Get recent periodic pump data
   ###########################################################
   def getRecentData(self):
      # Check if access token is valid
      if not self._is_token_valid(self.__tokenData):
         self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
         self._write_token_file(self.__tokenData, self.__tokenFile)
         if not self._is_token_valid(self.__tokenData):
            print("ERROR: unable to get valid access token")
            return False
         
      # Get data: first try
      data = self._get_data(self.__config, 
                            self.__tokenData, 
                            self.__username,
                            self.__role,
                            self.__patient["username"])
      # Check API response
      if self.__last_api_status in AUTH_ERROR_CODES:
         # Try to refresh token
         self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
         self._write_token_file(self.__tokenData, self.__tokenFile)
         
         # Get data: second try 
         data = self._get_data(self.__config, 
                               self.__tokenData, 
                               self.__username,
                               self.__role,
                               self.__patient["username"])
         # Check API response
         if self.__last_api_status in AUTH_ERROR_CODES:
            # Failed permanently
            print("ERROR: unable to get data")
            return False
      
      return data

   ###########################################################
   # Get last API response code
   ###########################################################
   def getLastResponseCode(self):
      return self.__last_api_status
   
   ###########################################################
   # Get Client library version
   ###########################################################
   def getClientVersion(self):
      return self.__version