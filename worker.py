# Maintained by ivan.kerezvo@tis.biz

import json
import boto3
from botocore.exceptions import ClientError, ParamValidationError
import urllib3
import os
import time
# This disables HTTPS requests warning skipping certificate check (the request is made ONLY via the internal network)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from random import randint
seconds = randint(1, 30)

# Global Variables coming from Environment variables of the Lambda function
ENVIRONMENT = os.environ['ENV']
REGION = os.environ['REGION']

# GET NOMAD TOKEN FROM SSM
def get_nomad_token ():
    ssm = boto3.client('ssm')
    NOMAD_TOKEN = ssm.get_parameter(Name='/' + ENVIRONMENT + '-aws-' + REGION + '/broker/secrets/NOMAD_TOKEN',WithDecryption=True)['Parameter']['Value']
    return NOMAD_TOKEN

# Get the AWS Instance ID via the event metadata, which is send via SNS
def get_instance_id(event, context):
    try:
        return json.loads(event['Records'][0]['Sns']['Message'])['EC2InstanceId']
    except KeyError:
        print("There is no such key in the provided dictionary (event metadata). Check the structure of the event payload")

# Get the private IP from the AWS Instance ID
def get_private_ip(event, context):
    ec2 = boto3.client('ec2', region_name = REGION)
    try:
        response = ec2.describe_instances(
            InstanceIds=[
                get_instance_id(event, context)
            ]
        )
        return response['Reservations'][0]['Instances'][0]['PrivateIpAddress']
    except ParamValidationError:
        print("Could not fetch the private IP of the instance. Check the instance ID function")

# Get the nomad agent ID with an API call (  https://www.nomadproject.io/api-docs/agent )
def get_nomad_self_id(event, context):
    http = urllib3.PoolManager()
    try:
        r = http.request('GET',
            'http://' + get_private_ip(event, context) + ':4646/v1/agent/self',
            timeout=3.0,
            headers={
                'X-Nomad-Token': get_nomad_token()
            }
        )
        return json.loads(r.data.decode('utf-8'))['stats']['client']['node_id']
    except urllib3.exceptions.MaxRetryError:
        print('Makre sure that the IP of the instance is correct')
    except json.JSONDecodeError:
        print('Check if the API endpoint is correct. Maybe something is changed in Nomad. Or check if the NOMAD token is correct')

# The main Lambda function. The NOMAD Drain API call (https://www.nomadproject.io/api-docs/nodes#drain-node)
# We make the API call TO THE NOMAD servers (ELB in front), NOT the individual clients.
def handler(event, context):
    time.sleep(seconds)
    payload = { "DrainSpec": { "Deadline": 3600000000000, "IgnoreSystemJobs": False } }
    encoded_data = json.dumps(payload).encode('utf-8')
    http = urllib3.PoolManager(cert_reqs='CERT_NONE', assert_hostname=False)
    r = http.request(
        'POST',
        'https://nomad.' + ENVIRONMENT + '-aws-' + REGION + '.tis.loc/v1/node/' + get_nomad_self_id(event, context) + '/drain',
        headers={
            'X-Nomad-Token': get_nomad_token()
        },
        body=encoded_data,
        timeout=3.0
    )
    print(seconds)
    print(r.status)
    print(r.data)
    print('Draining Worker with IP' + get_private_ip(event, context))


# TO DO
# Get answer back from NOMAD API that all jobs are stopped and TERMINATE the instance with BOTO3
# AT the moment the instance terminates based on the LifeCycle timeout which is 30 minutes

# def check_nomad_allocations ():
#     http = urllib3.PoolManager()
#     r = http.request('GET',
#         'http://10.4.133.235:4646/v1/node/d0fb58b9-8e9a-2869-b21c-df08d653af12/allocations',
#         timeout=3.0,
#         headers={
#             'X-Nomad-Token': '998022ea-81c5-bf8f-6339-af572adfe98e'
#         }
#     )
#     return (json.loads(r.data.decode('utf-8')))

