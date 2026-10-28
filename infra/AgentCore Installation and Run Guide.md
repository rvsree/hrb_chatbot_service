# AgentCore Installation and Run Guide

## Pre-Requisites

- Install [Docker Desktop](https://www.docker.com/get-started/)
- AWS Account
- Install [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- Setup IAM Role (`AdminRole`) for AWS CLI:

  ```bash
  aws configure
  ```

- Bedrock Model Access - NovaPro in `us-east-2`

---

## Steps to Deploy Agentic App on Bedrock AgentCore Runtime

### Step 1 - AgentCore Import

AgentCore imports → <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html>

### Step 2 - Add AgentCore Runtime Decorator in the code

A Python decorator within the Bedrock AgentCore SDK.

Function to be executed by the runtime on an event (prompt) and creates WebServer Endpoints:

| Endpoint | Method |
| --- | --- |
| `/invocations` | POST |
| `/ping` | GET |

### Step 3 - Create `requirements.txt` and run (root folder)

```bash
pip install -r requirements.txt
```

### Step 4 - Test locally

```bash
python src/vacation_planner/crew.py
curl http://localhost:8080/ping
```

### Step 5 - Docker Build & Deploy Commands

Create the `Dockerfile` in the root folder, then run:

```powershell
# Setup buildx
docker buildx create --use

# Create ECR repository
# (skip this if you already created the repo in the AWS Console)
#aws ecr create-repository --repository-name ai-workflows/vacation-planner-01 --region us-east-2
aws ecr create-repository --repository-name ai-workflows/vacation-planner-observability-01 --region us-east-2

# Login to ECR
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com

# Build and push
#docker buildx build --platform linux/arm64 -t <AWS_ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/ai-workflows/vacation-planner-01:latest --push .
docker buildx build --platform linux/arm64 -t <AWS_ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/ai-workflows/vacation-planner-observability-01:latest --push .

```

> **Important:** the first build can take up to 30 minutes due to the ARM64 architecture.

### Step 6 - Deploy from the AgentCore Service

From the AgentCore Service, deploy the Agentic AI App with the image in ECR.

### Step 7 - Test the endpoint

Sample payload:

```json
{
  "topic": "Plan a vacation to Bali, Indonesia"
}
```

### Step 8 - Create AWS Lambda function and API Gateway

### Step 9 - Test in Postman

Step-by-step in Postman:

- **Set Method:** select `POST`
- **Enter URL:** paste the API Gateway URL
- **Add Header:** Key `Content-Type`, Value `application/json`
- **Set Body:** select `raw`, choose `JSON` from the dropdown, paste the JSON payload

Sample payload to test:

```json
{
  "prompt": "Plan a 7-day vacation to New York"
}
```

### Step 10 - Deploy UI using Streamlit

- Add Streamlit file
- Replace with your API endpoint
- Install and run:

  ```bash
  pip install streamlit
  streamlit run streamlit_api.py   # replace with your streamlit file name
  ```

---

**End**

---

## 2. AgentCore Observability (Metrics, Logs and Traces)

Uses the OpenTelemetry library (open source) - **aws-opentelemetry-distro** (ADOT).

<https://opentelemetry.io/docs/collector/distributions/>

### Step 1 - Add `aws-opentelemetry-distro` in `requirements.txt`

### Step 2 - Add `aws-opentelemetry-distro` in the Dockerfile

### Step 3 - Application Signals (APM) and choose Transaction search ---> Enable Transaction Search (toggle it ON) -- `aws/spans`

### Step 5 - Enable Model invocation Logging

### Step 6 - Build the image and push to repo

### Step 7 - Update the AgentCore Runtime Configuration from Console

### Step 8 - Add IAM Permissions to the Role used by the AgentCore Runtime

### Step 9 - Wait 5-10 minutes for changes to take effect

---

**End**
