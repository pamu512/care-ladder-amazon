#!/usr/bin/env bash
# Reproducible provisioning of the Care Ladder AWS demo stack (us-east-1).
#
# This script documents EXACTLY how the live stack was created — it is the
# source of truth behind infra/README.md. It provisions:
#   VPC bits (subnets/sg) → ECR repo → ECS cluster + Fargate service →
#   ALB (internet-facing) → CloudFront HTTPS → DynamoDB table → task role
#
# Idempotent-ish: existing resources are detected and reused (no blind
# re-create). Run from repo root with a `care-ladder` AWS profile.
#
# NOTE: this is the CREATE-TIME record. The live stack was provisioned
# interactively during the hackathon; this script replays those commands in
# order. Day-2 operations (deploy new image) are in scripts/deploy.sh.
set -euo pipefail

PROFILE="${AWS_PROFILE:-care-ladder}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
ECR_REPO="care-ladder"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
CLUSTER="care-ladder-demo"
SERVICE="care-ladder-demo"
TABLE="care-ladder-incidents"
BUCKET="care-ladder-demo-${ACCOUNT_ID}"

echo "account: $ACCOUNT_ID  region: $REGION"

# ---------- 1. ECR ----------
if ! aws ecr describe-repositories --profile "$PROFILE" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
  aws ecr create-repository --profile "$PROFILE" --repository-name "$ECR_REPO" \
    --image-scanning-configuration scanOnPush=true \
    --query 'repository.repositoryUri' --output text
fi
echo "ECR: $ECR_URI"

# ---------- 2. VPC: default VPC subnets + security group ----------
SUBNETS=$(aws ec2 describe-subnets --profile "$PROFILE" \
  --filters "Name=default-for-az,Values=true" \
  --query 'Subnets[].Id' --output text | tr '\t' ' ')
if ! aws ec2 describe-security-groups --profile "$PROFILE" --group-ids sg-0cf7084f27c11941c >/dev/null 2>&1; then
  SG_ID=$(aws ec2 create-security-group --profile "$PROFILE" \
    --group-name care-ladder-demo --description "care-ladder demo tasks" \
    --query 'GroupId' --output text)
  aws ec2 authorize-security-group-ingress --profile "$PROFILE" --group-id "$SG_ID" \
    --protocol tcp --port 8000 --cidr $(aws ec2 describe-vpcs --profile "$PROFILE" --vpc-ids "$VPC_ID" --query 'Vpcs[0].CidrBlock' --output text) >/dev/null
else
  SG_ID=sg-0cf7084f27c11941c
fi
VPC_ID=$(aws ec2 describe-subnets --profile "$PROFILE" --subnet-ids $(echo $SUBNETS | awk '{print $1}') --query 'Subnets[0].VpcId' --output text)
echo "subnets: $SUBNETS"
echo "vpc: $VPC_ID"
echo "sg: $SG_ID"

# ---------- 3. DynamoDB ----------
if ! aws dynamodb describe-table --profile "$PROFILE" --table-name "$TABLE" >/dev/null 2>&1; then
  aws dynamodb create-table --profile "$PROFILE" --table-name "$TABLE" \
    --attribute-definitions AttributeName=incident_id,AttributeType=S \
    --key-schema AttributeName=incident_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
fi
echo "dynamodb: $TABLE"

# ---------- 4. S3 (privacy-filtered incident clips) ----------
if ! aws s3api head-bucket --profile "$PROFILE" --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3api create-bucket --profile "$PROFILE" --bucket "$BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  aws s3api put-public-access-block --profile "$PROFILE" --bucket "$BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi
echo "s3: s3://$BUCKET"

# ---------- 5. ECS cluster ----------
if ! aws ecs list-clusters --profile "$PROFILE" --query 'clusterArns' --output text | grep -q "$CLUSTER"; then
  aws ecs create-cluster --profile "$PROFILE" --cluster-name "$CLUSTER" >/dev/null
fi
echo "ecs cluster: $CLUSTER"

# ---------- 6. task definition + service ----------
# Task def references the task role + image; register current infra/task-definition.json
TASK_DEF_ARN=$(aws ecs register-task-definition --profile "$PROFILE" \
  --cli-input-json file://infra/task-definition.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "task def: $TASK_DEF_ARN"

# ALB + target group + listener (internet-facing)
if ! aws elbv2 describe-load-balancers --profile "$PROFILE" --names care-ladder-demo >/dev/null 2>&1; then
  TG_ARN=$(aws elbv2 create-target-group --profile "$PROFILE" \
    --name care-ladder-demo --protocol HTTP --port 8000 --vpc-id "$VPC_ID" \
    --target-type ip --health-check-path /incidents \
    --query 'TargetGroups[0].TargetGroupArn' --output text)
  ALB_ARN=$(aws elbv2 create-load-balancer --profile "$PROFILE" \
    --name care-ladder-demo --scheme internet-facing --type application \
    --subnets $SUBNETS --query 'LoadBalancers[0].LoadBalancerArn' --output text)
  aws elbv2 create-listener --profile "$PROFILE" --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 --default-actions \
    Type=forward,TargetGroupArn="$TG_ARN" >/dev/null
fi
ALB_DNS=$(aws elbv2 describe-load-balancers --profile "$PROFILE" --names care-ladder-demo \
  --query 'LoadBalancers[0].DNSName' --output text)
echo "ALB: $ALB_DNS"

# service
if ! aws ecs list-services --profile "$PROFILE" --cluster "$CLUSTER" --query 'serviceArns' --output text | grep -q "$SERVICE"; then
  aws ecs create-service --profile "$PROFILE" --cluster "$CLUSTER" --service-name "$SERVICE" \
    --task-definition "$TASK_DEF_ARN" --desired-count 1 --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=$TG_ARN,containerName=care-ladder,containerPort=8000" >/dev/null
fi
echo "service: $SERVICE (desired 1, Fargate, public IP)"

# ---------- 7. CloudFront ----------
# origin = ALB, viewer HTTPS → origin HTTP, default behavior * → ALB
if ! aws cloudfront list-distributions --profile "$PROFILE" --query 'DistributionList.Items[].Origins.Items[0].DomainName' --output text | grep -q "$ALB_DNS"; then
  TMP=$(mktemp -d)
  cat > "$TMP/cf.json" <<CFEOF
{
  "CallerReference": "care-ladder-demo-$(date +%s)",
  "Comment": "Care Ladder demo HTTPS front",
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "alb",
      "DomainName": "$ALB_DNS",
      "CustomOriginConfig": {
        "OriginProtocolPolicy": "http-only",
        "OriginReadTimeout": 60,
        "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] }
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "alb",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": { "Quantity": 7, "Items": ["GET","HEAD","POST","PUT","PATCH","OPTIONS","DELETE"] },
    "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] },
    "ForwardedValues": { "QueryString": true, "Cookies": { "Value": "all" }, "Headers": { "Quantity": 0 } },
    "MinTTL": 0, "DefaultTTL": 0, "MaxTTL": 0,
    "TrustedSigners": { "Quantity": 0 }
  },
  "Enabled": true
}
CFEOF
  aws cloudfront create-distribution --profile "$PROFILE" --distribution-config file://"$TMP/cf.json" \
    --query 'Distribution.DomainName' --output text
fi
CF_DNS=$(aws cloudfront list-distributions --profile "$PROFILE" \
  --query "DistributionList.Items[?Origins.Items[0].DomainName=='$ALB_DNS'].DomainName" --output text)
echo "CloudFront: $CF_DNS"

# ---------- 8. EventBridge cue archive (bus -> CloudWatch Logs) ----------
# The API PutEvents cues to bus "$BUS" (source care.ladder). Without a rule
# they vanish; archive them so judges can inspect delivered events.
BUS="care-ladder"
if ! aws events list-rules --profile "$PROFILE" --event-bus-name "$BUS" --query 'Rules[].Name' --output text | grep -q care-ladder-cue-archive; then
  aws logs create-log-group --profile "$PROFILE" --log-group-name /aws/events/care-ladder-cues 2>/dev/null || true
  aws events put-rule --profile "$PROFILE" --event-bus-name "$BUS" \
    --name care-ladder-cue-archive --event-pattern '{"source":["care.ladder"]}' >/dev/null
  aws events put-targets --profile "$PROFILE" --event-bus-name "$BUS" \
    --rule care-ladder-cue-archive \
    --targets "Id"="cues-to-logs","Arn"="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/events/care-ladder-cues" >/dev/null
  python3 - "$REGION" "$ACCOUNT_ID" <<'PYEOF'
import json, subprocess, sys
region, account = sys.argv[1], sys.argv[2]
policy = {"Statement": [{
    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
    "Effect": "Allow",
    "Principal": {"Service": "events.amazonaws.com"},
    "Resource": f"arn:aws:logs:{region}:{account}:log-group:/aws/events/care-ladder-cues:*",
    "Sid": "TrustEventsToWriteLogGroup",
}], "Version": "2012-10-17"}
subprocess.run(["aws", "logs", "put-resource-policy", "--profile", "care-ladder",
                "--policy-name", "care-ladder-eventbridge-to-logs",
                "--policy-document", json.dumps(policy)], check=True, capture_output=True)
PYEOF
fi
echo "eventbridge archive: bus $BUS -> /aws/events/care-ladder-cues"

echo
echo "stack ready:"
echo "  health:   curl http://$ALB_DNS/v1/health"
echo "  https:    https://$CF_DNS/v1/health"
