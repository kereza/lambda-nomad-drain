# Python code  designed for HashiCorp NOMAD and AWS Auto Scaling Group Events to tirgger autmatic draining of containers.

It works in the following way:



1. Secrets like the NOMAD token are stored in the AWS SSM Secret Manager
2. When Auto Scaling Group event to terminate an instance is triggered - the even ID with the instance metadata is sent to Lambda
3. The python code gets the IP of the instance via the metadata
4. It communicates with the NOMAD API and schedules a DRAIN for the IP/ID of the worker/instances that is going ot be terminated
5. Note that you need to configure your ASG to terminate the instances with some delay, so the Docker containers have enough time to DRAIN