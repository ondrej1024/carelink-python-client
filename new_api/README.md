# Carelink Python Client
*Medtronic CareLink Client implemented in Python*

Python library, which can be used for retrieving data from Medtronic CareLink of online CGM and insulin pump device data uploads (Guardian Connect, MiniMed 7xxG). 



## Status

This is a developer version. Works for me. Extensive testing of different use cases is needed. Please report back if it works also or you.



## Supported devices

- [Medtronic Guardian Connect CGM](https://hcp.medtronic-diabetes.com.au/guardian-connect) (*to be confirmed*)

- [Medtronic MiniMed 770G pump](https://www.medtronicdiabetes.com/products/minimed-770g-insulin-pump-system) (*to be confirmed*)

- [Medtronic MiniMed 780G pump](https://www.medtronic-diabetes.co.uk/insulin-pump-therapy/minimed-780g-system)

  

## Features

- Works with Carelink patient and follower account
- Automatic refresh of access token 
- Local storage of token data
- Function for downloading current pump and sensor status plus last 24h data from CareLink Cloud
- CareLink Client CLI (console example program)
- CareLink Client Proxy (daemon example program for providing the CareLink data in the local network)



## Limitations

- CareLink MFA is not supported




## Requirements

- CareLink account (with MFA NOT ENABLED)

  - Guardian Connect CGM outside US: **not tested yet!**  
  - Guardian Connect CGM inside US: **not tested yet!** 
  - 7xxG pump: patient or care partner account (same as for Medtronic CareLink Connect app)
- Runtime: Python3
- External libraries used:

  - Python Requests



## How to use

### Clone this repository

```
git clone https://github.com/ondrej1024/carelink-python-client.git
cd carelink-python-client/new_api
```

### Get login data

The Carelink Client library needs the initial login data stored in the `logindata.json` file. This file is created by running the login script on a PC with a screen:

```
python carelink_carepartner_api_login.py 
```

You might need to install the following Python packages to satisfy the scripts dependencies:

```
- requests
- curlify
- OpenSSL
- seleniumwire
```

The script opens a Firefox web browser with the Carelink login page. You have to provide your Carelink patients or follower credentials and solve the reCapcha. On successful completion of the login the data file will be created. 

The Carelink Client reads this file from the local folder and it will take care of refreshing automatically the login data when it expires. It should be able to do so within one week of the last refresh.

### Get periodic pump and sensor data

#### Carelink Client library

`carelink_client2.py` is a Python module that can be used in your own Python application.

    import carelink_client2
    
    client = carelink_client2.CareLinkClient(tokenFile="logindata.json")
    if client.init():
        client.printUserInfo()
        recentData = client.getRecentData()

#### Carelink Client CLI

`carelink_client2_cli.py` is an example Python application which uses the `carelink_client2` library to download the patients Carelink data via command line.

    python carelink_client2_cli.py -d

##### Get CLI options

    python carelink_client2_cli.py -h

#### Carelink Client Proxy

`carelink_client2_proxy.py` is a Python application which uses the `carelink_client2` library. It runs as a service and downloads the patients Carelink data periodically and provide it via a simple REST API to clients in the local network.

    python carelink_client2_proxy.py

##### Get CLI options

    python carelink_client2_proxy.py -h

##### API endpoints

The proxy provides the following API endpoints which can be queried with an HTTP `GET` request:

* `<proxy IP address>:8081` (Status info)
* `<proxy IP address>:8081/carelink` (complete data, in json format)
* `<proxy IP address>:8081/carelink/nohistory` (only current data without last 24h history, in json format)

For documentation of the data format see [carelink-data.ods](../doc/carelink-data.ods)


##### Systemd service

To run the proxy automatically at system start it can be installed as systemd service using the provided service file:

[systemd/carelink2-proxy.service](systemd/carelink2-proxy.service)



## Credits

This project is based on other peoples work which I want to thank for their efforts.

* [Pal Marci](https://github.com/palmarci) for discovering the Carelink Cloud API communication of the "Carelink Connect" app

* [Bence Szász](https://github.com/benceszasz) for the Java implementation of the [xDrip Carelink Follower](https://github.com/NightscoutFoundation/xDrip/tree/master/app/src/main/java/com/eveningoutpost/dexdrip/cgm/carelinkfollow)

  


## Disclaimer

This project is intended for educational and informational purposes only. It relies on a series of fragile components and assumptions, any of which may break at any time. It is not FDA approved and should not be used to make medical decisions. It is neither affiliated with nor endorsed by Medtronic, and may violate their Terms of Service. Use of this code is without warranty or formal support of any kind.
