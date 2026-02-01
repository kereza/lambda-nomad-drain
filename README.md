# Lambda Nomad Drain

An AWS Lambda function that automatically drains HashiCorp Nomad worker nodes when AWS Auto Scaling Group (ASG) instances are scheduled for termination. This ensures graceful container shutdown and prevents service disruption during scale-down events.

## How It Works

```
ASG Termination Event
         ↓
    SNS Topic
         ↓
   Lambda Function
         ↓
    ┌────┴────┐
    ↓         ↓
AWS EC2    Nomad Agent API
  API      (get node ID)
    ↓         ↓
    └────┬────┘
         ↓
  Nomad Server API
  (initiate drain)
```

1. **ASG Lifecycle Hook** triggers when an instance is marked for termination
2. **SNS notification** is sent to Lambda with instance metadata
3. **Lambda retrieves** the Nomad authentication token from AWS SSM Parameter Store
4. **Lambda queries** AWS EC2 API to get the instance's private IP address
5. **Lambda calls** the Nomad Agent API on the instance to get the Nomad node ID
6. **Lambda initiates** a drain operation via the Nomad Server API (through ELB)
7. **Nomad drains** all allocations from the node over a 1-hour deadline
8. **ASG terminates** the instance after the lifecycle hook timeout (default: 30 minutes)

## Prerequisites

### AWS Resources
- **Lambda Function** with Python 3.x runtime
- **IAM Role** with permissions:
  - `ssm:GetParameter` for retrieving Nomad token
  - `ec2:DescribeInstances` for getting instance details
  - VPC access to reach Nomad agents on port 4646
- **SNS Topic** subscribed to ASG lifecycle hooks
- **ASG Lifecycle Hook** configured with:
  - Lifecycle transition: `autoscaling:EC2_INSTANCE_TERMINATING`
  - Heartbeat timeout: 1800 seconds (30 minutes) minimum
  - Default result: `CONTINUE`

### Nomad Configuration
- Nomad agents running on ASG instances
- Nomad servers accessible via internal DNS: `nomad.{ENV}-aws-{REGION}.tis.loc`
- Valid Nomad token with node drain permissions stored in SSM

## Deployment

### 1. Store Nomad Token in SSM
```bash
aws ssm put-parameter \
  --name "/{ENV}-aws-{REGION}/broker/secrets/NOMAD_TOKEN" \
  --value "your-nomad-token" \
  --type "SecureString" \
  --region {REGION}
```

### 2. Create Lambda Deployment Package
```bash
# Install dependencies
pip install boto3 urllib3 -t package/

# Add function code
cp worker.py package/

# Create ZIP
cd package && zip -r ../lambda-nomad-drain.zip . && cd ..
```

### 3. Deploy Lambda Function
```bash
aws lambda create-function \
  --function-name lambda-nomad-drain \
  --runtime python3.9 \
  --handler worker.handler \
  --zip-file fileb://lambda-nomad-drain.zip \
  --role arn:aws:iam::{ACCOUNT_ID}:role/{LAMBDA_ROLE} \
  --timeout 30 \
  --environment Variables={ENV={ENV},REGION={REGION}}
```

### 4. Subscribe Lambda to SNS Topic
```bash
aws sns subscribe \
  --topic-arn arn:aws:sns:{REGION}:{ACCOUNT_ID}:{SNS_TOPIC} \
  --protocol lambda \
  --notification-endpoint arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:lambda-nomad-drain
```

### 5. Configure ASG Lifecycle Hook
```bash
aws autoscaling put-lifecycle-hook \
  --lifecycle-hook-name nomad-drain-hook \
  --auto-scaling-group-name {ASG_NAME} \
  --lifecycle-transition autoscaling:EC2_INSTANCE_TERMINATING \
  --notification-target-arn arn:aws:sns:{REGION}:{ACCOUNT_ID}:{SNS_TOPIC} \
  --role-arn arn:aws:iam::{ACCOUNT_ID}:role/{ASG_ROLE} \
  --heartbeat-timeout 1800 \
  --default-result CONTINUE
```

## Configuration

### Environment Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | Environment name | `prod`, `staging`, `dev` |
| `REGION` | AWS region | `us-east-1`, `eu-west-1` |

### SSM Parameter
- **Path**: `/{ENV}-aws-{REGION}/broker/secrets/NOMAD_TOKEN`
- **Type**: SecureString
- **Value**: Nomad ACL token with drain permissions

### Drain Configuration
The drain is configured with:
- **Deadline**: 1 hour (3600000000000 nanoseconds)
- **IgnoreSystemJobs**: False (system jobs are also drained)

To modify these settings, edit the `payload` in `worker.py:65`:
```python
payload = {
    "DrainSpec": {
        "Deadline": 3600000000000,  # 1 hour in nanoseconds
        "IgnoreSystemJobs": False
    }
}
```

## Troubleshooting

### Lambda fails with "Could not fetch the private IP"
- Verify the instance ID is being correctly extracted from the SNS message
- Check that the Lambda IAM role has `ec2:DescribeInstances` permission
- Ensure the instance hasn't already been terminated

### Lambda fails with "Makre sure that the IP of the instance is correct"
- Verify Lambda has network access to the instance on port 4646
- Check VPC configuration and security groups
- Confirm the instance is running a Nomad agent

### Drain doesn't complete before termination
- Increase ASG lifecycle hook timeout (currently 30 minutes)
- Reduce drain deadline in the code (currently 1 hour)
- Check Nomad logs to see if allocations are failing to stop

### "Check if the NOMAD token is correct" error
- Verify the SSM parameter path matches: `/{ENV}-aws-{REGION}/broker/secrets/NOMAD_TOKEN`
- Confirm the token has valid drain permissions in Nomad
- Check the token hasn't expired (if using time-limited ACLs)

## Limitations

1. **No automated termination**: The function doesn't verify that draining completed successfully before the instance terminates. Instance termination relies solely on the ASG lifecycle hook timeout.

2. **No retry logic**: If Nomad API calls fail, the function doesn't retry. The instance will terminate after the lifecycle timeout.

3. **Disabled certificate verification**: TLS certificate validation is disabled for Nomad server API calls (`cert_reqs='CERT_NONE'`).

4. **Thundering herd mitigation**: A random 1-30 second sleep is used when multiple instances terminate simultaneously. This is a basic mitigation that may not be sufficient for large-scale terminations.

## Future Improvements

Potential enhancements (see `worker.py:83-85` for TODOs):
- Poll Nomad API to verify all allocations are stopped
- Automatically call ASG Complete Lifecycle Action when drain completes
- Add proper error handling and retry logic
- Enable certificate verification for Nomad API calls
- Add CloudWatch metrics and alarms
- Support multiple Nomad regions/clusters