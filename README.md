# Carelink Python Client
*Experimental Medtronic CareLink Client in Python*

Python library, which can be used for retrieving data from Medtronic CareLink of online CGM and insulin pump device data uploads (Guardian Connect, MiniMed 7xxG) inside and outside of US. 

This is a port of the Java library [CareLinkJavaClient]( https://github.com/benceszasz/CareLinkJavaClient)



## Status

This is a developer version. Works for me. Extensive testing of different use cases is needed. Please report back if it works also or you.



## Supported devices

- [Medtronic Guardian Connect CGM](https://hcp.medtronic-diabetes.com.au/guardian-connect) (*to be confirmed*)

- [Medtronic MiniMed 770G pump](https://www.medtronicdiabetes.com/products/minimed-770g-insulin-pump-system) (*to be confirmed*)

- [Medtronic MiniMed 780G pump](https://www.medtronic-diabetes.co.uk/insulin-pump-therapy/minimed-780g-system)

  

## Features

- Login to CareLink and provide access token for CareLink API calls
- Some basic CareLink APIs: get user data, get user profile, get  country settings, get last 24 hours, get recent data from CareLink Cloud
- Wrapper method for getting data uploaded by Medtronic BLE devices of the last 24 hours
- CareLink Client CLI



## Limitations

- CareLink MFA is not supported
- Notification messages are in English




## Requirements

- CareLink account (with MFA NOT ENABLED)

  - Guardian Connect CGM outside US: patient or care partner account
  - Guardian Connect CGM inside US: **not tested yet!** (possibly a care partner account)
  - 7xxG pump outside US: care partner account (same as for Medtronic CareLink Connect app)
  - 7xxG pump inside US: care partner account (same as for Medtronic CareLink Connect app)

- Runtime: Python3

- External libraries used:

  - Python Requests



## How to use

### Clone this repository

```
git clone https://github.com/ondrej1024/carelink-python-client.git
cd carelink-python-client
```

### Get data of last 24 hours using Python

    import carelink_client
    
    client = carelink_client.CareLinkClient("carelink_username", "carelink_password", "carelink_country_code", "patient_id")
    if client.login():
        recentData = client.getRecentData()

### Download last 24 hours using CLI

    python carelink_client_cli.py -u carelink_username -p carelink_password -c carelink_country_code -d

### Get CLI options

    python carelink_client_cli.py -h




## Credits

This project is based on other peoples work which I want to thank for their efforts.

* [Bence Szász](https://github.com/benceszasz) for the original  Java implementation
* [Ben West](https://github.com/bewest) for providing valuable details on the Carelink API and workflow




## Disclaimer

This project is intended for educational and informational purposes only. It relies on a series of fragile components and assumptions, any of which may break at any time. It is not FDA approved and should not be used to make medical decisions. It is neither affiliated with nor endorsed by Medtronic, and may violate their Terms of Service. Use of this code is without warranty or formal support of any kind.
